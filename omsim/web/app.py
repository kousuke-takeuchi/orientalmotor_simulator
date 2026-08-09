"""シミュレータの状態をブラウザへ配る FastAPI アプリ。

Web が落ちてもシミュレーション本体は動き続ける。ここは snapshot の
購読者に徹し、シミュレーション状態を書き換えない。
"""
import asyncio
import json
import logging
import os
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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


def run_web(hub, host="0.0.0.0", port=8080):
    """uvicorn をバックグラウンドスレッドで起動し (server, thread) を返す。"""
    import uvicorn

    config = uvicorn.Config(
        create_app(hub), host=host, port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread
