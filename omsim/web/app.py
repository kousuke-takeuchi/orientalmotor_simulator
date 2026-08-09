"""シミュレータの状態をブラウザへ配る FastAPI アプリ。

Web が落ちてもシミュレーション本体は動き続ける。ここは基本的に snapshot の
購読者に徹する。唯一の例外が /api/wiring で、CN4 の配線と安全リレーだけは
ここから書き換える (CAN 上に現れない物理配線を操作する手段が他に無いため)。
"""
import asyncio
import json
import logging
import os
import threading

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from omsim.sim.wiring import WiringError

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PUSH_INTERVAL_SECONDS = 0.1

logger = logging.getLogger(__name__)

# starlette.websockets.WebSocket.send() がクローズ後の二重送信で出す文言。
# 実測(uvicorn 0.33 + starlette 0.44, real TCP): クライアントが切断すると
# 最初の send_text() は starlette.websockets.WebSocketDisconnect を送出する
# (uvicorn の ClientDisconnected/OSError を starlette が変換したもの)。
# その状態のままさらに send_text() を呼ぶと、今度はこの RuntimeError になる。
# どちらも「切断済みソケットへ書きに行った」という同じ事象の別表現なので、
# 両方とも通常の切断として静かに終了させる。
_ALREADY_CLOSED_MESSAGE = 'Cannot call "send" once a close message has been sent.'


def _json_default(value):
    """json.dumps に渡せない値が来たら、黙って文字列化せず警告を残す。"""
    logger.warning(
        "websocket_state: JSON化できない値を検出したため str() で代替します: %r",
        value,
    )
    return str(value)


def create_app(hub):
    app = FastAPI(title="omsim")

    @app.get("/api/state")
    def get_state():
        return hub.payload()

    @app.get("/api/wiring")
    def get_wiring():
        try:
            return hub.wiring()
        except WiringError as err:
            # 再生モードは配線を持たない。500 ではなく「今は無い」と返す。
            raise HTTPException(status_code=409, detail=str(err))

    @app.get("/api/replay")
    def get_replay():
        if not hasattr(hub, "seek"):
            raise HTTPException(status_code=404, detail="再生モードではありません")
        return hub.state()

    @app.post("/api/replay")
    def post_replay(body: dict):
        if not hasattr(hub, "seek"):
            raise HTTPException(status_code=404, detail="再生モードではありません")
        if "position" in body:
            hub.seek(body["position"])
        if "playing" in body:
            hub.set_playing(body["playing"])
        return hub.state()

    @app.post("/api/wiring")
    def post_wiring(body: dict):
        # 監視だけの他のエンドポイントと違い、ここはシミュレーション状態を
        # 書き換える (CN4 の配線と安全リレー)。
        try:
            return hub.set_wiring(
                preset=body.get("preset"),
                hwto1=body.get("hwto1"),
                hwto2=body.get("hwto2"),
                relay=body.get("relay"),
            )
        except WiringError as err:
            # 再生モードは配線を持たない。設定ミス (400) ではなく、
            # 今の状態では実行できない (409) として区別する。
            status = 409 if hasattr(hub, "seek") else 400
            raise HTTPException(status_code=status, detail=str(err))

    @app.get("/api/stubs")
    def get_stubs():
        from omsim.driver.model import DriverModel

        return {
            "stubs": [
                {"index": index, "sub": sub, "reason": reason}
                for index, sub, reason in DriverModel.router.stubs()
            ]
        }

    @app.get("/")
    def get_index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/favicon.ico")
    def get_favicon():
        # ファビコンは持たない。204 を返してブラウザの 404 ノイズだけ消す。
        return Response(status_code=204)

    @app.websocket("/ws")
    async def websocket_state(socket: WebSocket):
        # 型注釈は必須。FastAPI はこれを見て WebSocket 引数だと判断する。
        await socket.accept()
        try:
            while True:
                await socket.send_text(json.dumps(hub.payload(), default=_json_default))
                await asyncio.sleep(PUSH_INTERVAL_SECONDS)
        except WebSocketDisconnect:
            # 通常の切断。ログを汚さず静かに終了する。
            return
        except RuntimeError as exc:
            if str(exc) == _ALREADY_CLOSED_MESSAGE:
                # 切断済みソケットへ送ろうとした場合の別表現。これも通常の切断。
                return
            logger.warning("websocket_state: 予期しないエラーで接続を終了します: %r", exc)
            return
        except Exception as exc:  # noqa: BLE001 想定外の例外は握りつぶさず記録する
            logger.warning("websocket_state: 予期しないエラーで接続を終了します: %r", exc)
            return

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def run_web(hub, host="127.0.0.1", port=8080):
    """uvicorn をバックグラウンドスレッドで起動し (server, thread) を返す。"""
    import uvicorn

    config = uvicorn.Config(
        create_app(hub), host=host, port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread
