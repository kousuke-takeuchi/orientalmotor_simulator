"""シミュレータの状態をブラウザへ配る FastAPI アプリ。

Web が落ちてもシミュレーション本体は動き続ける。ここは snapshot の
購読者に徹し、シミュレーション状態を書き換えない。
"""
import asyncio
import json
import os
import threading

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PUSH_INTERVAL_SECONDS = 0.1


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
                await socket.send_text(json.dumps(hub.payload(), default=str))
                await asyncio.sleep(PUSH_INTERVAL_SECONDS)
        except WebSocketDisconnect:
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
