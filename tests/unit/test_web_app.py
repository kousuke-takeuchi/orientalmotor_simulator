import asyncio
import json
import logging
import threading
import time

import uvicorn
import websockets
from fastapi.testclient import TestClient

from omsim.node.eds import DEFAULT_EDS_PATH
from omsim.sim.manager import NodeManager, NodeSpec
from omsim.sim.recorder import Recorder
from omsim.web.app import create_app
from omsim.web.hub import SnapshotHub


def make_client():
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=None, realtime=False)
    recorder = Recorder(None)
    hub = SnapshotHub(manager, recorder)
    manager.step()
    hub.capture()
    return TestClient(create_app(hub)), manager, recorder


def test_state_endpoint_returns_every_node():
    client, _manager, recorder = make_client()
    body = client.get("/api/state").json()
    assert sorted(body["nodes"]) == ["1", "2"]
    assert "sim_time" in body
    recorder.close()


def test_state_endpoint_includes_frames():
    client, _manager, recorder = make_client()
    body = client.get("/api/state").json()
    assert isinstance(body["frames"], list)
    recorder.close()


def test_stubs_endpoint_lists_unimplemented_objects():
    client, _manager, recorder = make_client()
    body = client.get("/api/stubs").json()
    assert len(body["stubs"]) > 0
    entry = body["stubs"][0]
    assert set(entry) == {"index", "sub", "reason"}
    recorder.close()


def test_root_serves_the_page():
    client, _manager, recorder = make_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "omsim" in response.text.lower()
    recorder.close()


def test_websocket_sends_a_payload_on_connect():
    client, _manager, recorder = make_client()
    with client.websocket_connect("/ws") as socket:
        payload = json.loads(socket.receive_text())
    assert sorted(payload["nodes"]) == ["1", "2"]
    recorder.close()


class _RaisingHub:
    """hub.payload() が切断以外の予期しない例外を出すことをシミュレートする偽 hub。"""

    def payload(self):
        raise ValueError("boom - unexpected payload failure")


def test_websocket_unexpected_error_is_logged_not_swallowed(caplog):
    """切断以外の予期しない例外は、握りつぶさず logging で警告として残ること。

    実測: TestClient のインプロセス偽トランスポートでは、ws ハンドラ内で
    捕捉されずに伝播した例外は WebSocketTestSession._run() の
    `except BaseException as exc: self._send_queue.put(exc); raise` に
    乗り、`with` ブロックを抜ける際にそのまま再送出される。
    つまり未修正のコードでは、この with ブロックの外側で ValueError が
    そのまま漏れてテストが失敗する。
    """
    client = TestClient(create_app(_RaisingHub()))
    with caplog.at_level(logging.WARNING):
        with client.websocket_connect("/ws"):
            pass
    assert any(
        "boom - unexpected payload failure" in message for message in caplog.messages
    )


class _Unserializable:
    """json.dumps が素通しできない、独自 __repr__ を持つだけのオブジェクト。"""

    def __repr__(self):
        return "<_Unserializable sentinel>"


class _StubHub:
    def __init__(self, payload):
        self._payload = payload

    def payload(self):
        return self._payload


def test_websocket_logs_and_stringifies_unserializable_payload_values(caplog):
    """json.dumps に渡せない値が混ざっていたら、警告を出しつつ文字列化して送る。

    default=str のように黙って文字列化するのではなく、専用関数が呼ばれて
    ログに残ることを確認する。
    """
    payload = {
        "nodes": {},
        "sim_time": 0.0,
        "frames": [],
        "weird": _Unserializable(),
    }
    client = TestClient(create_app(_StubHub(payload)))
    with caplog.at_level(logging.WARNING):
        with client.websocket_connect("/ws") as socket:
            body = json.loads(socket.receive_text())
    assert body["weird"] == str(_Unserializable())
    assert any("_Unserializable" in message for message in caplog.messages)


def test_websocket_disconnect_does_not_log_a_warning():
    """クライアントが切断しても、切断は警告ログを残さず静かに終わること。

    実測: TestClient のインプロセス偽トランスポートは、with ブロックを
    抜けたときの切断をタスクキャンセルとして扱い、ws ハンドラの
    send_text() 失敗を再現しない(starlette.testclient の
    WebSocketTestSession._asgi_send はメッセージをキューに積むだけで、
    実際のソケットクローズによる失敗を模倣しない)。
    そのため、この切断シナリオは実際の uvicorn サーバ + 実 TCP の
    websockets クライアントで検証する。実測した例外は、1 回目の
    send_text() で starlette.websockets.WebSocketDisconnect
    (uvicorn の ClientDisconnected 経由)、もし送信を継続すれば
    2 回目以降は RuntimeError('Cannot call "send" once a close message
    has been sent.') だった。
    """
    specs = [
        NodeSpec(node_id=1, eds=DEFAULT_EDS_PATH),
        NodeSpec(node_id=2, eds=DEFAULT_EDS_PATH),
    ]
    manager = NodeManager(specs, network=None, realtime=False)
    recorder = Recorder(None)
    hub = SnapshotHub(manager, recorder)
    manager.step()
    hub.capture()

    config = uvicorn.Config(
        create_app(hub), host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "uvicorn サーバが起動しなかった"
        port = server.servers[0].sockets[0].getsockname()[1]

        records = []

        class _CollectingHandler(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = _CollectingHandler(level=logging.WARNING)
        app_logger = logging.getLogger("omsim.web.app")
        app_logger.addHandler(handler)
        try:
            async def connect_then_disconnect():
                url = "ws://127.0.0.1:%d/ws" % port
                async with websockets.connect(url) as ws_client:
                    await ws_client.recv()
                # `async with` を抜けると close ハンドシェイクが送られる。
                # サーバ側が切断を検知して ws ハンドラを終えるまで待つ。
                await asyncio.sleep(1.0)

            asyncio.run(connect_then_disconnect())
        finally:
            app_logger.removeHandler(handler)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        recorder.close()

    assert not records, "切断だけで警告ログが出てはいけない: %r" % (
        [r.getMessage() for r in records]
    )


def test_snapshot_exposes_increments_per_revolution_for_the_3d_view():
    """3D 表示の回転角計算に使う。JS 側に定数を二重に持たせないための口。"""
    from omsim.driver.model import DriverModel

    snapshot = DriverModel(node_id=1).snapshot()
    assert snapshot["increments_per_revolution"] == 3600


# --- 配線 / 安全リレーの操作 (P3.5) ---

def test_wiring_endpoint_reports_the_current_wiring():
    client, _manager, recorder = make_client()
    body = client.get("/api/wiring").json()
    assert body["preset"] == "standard"
    assert body["hwto1"]["source"] == "relay"
    assert body["hwto1"]["pins"] == "CN4 11/12"
    assert body["relay"] is True
    assert body["inputs"] == {"hwto1_on": True, "hwto2_on": True}
    recorder.close()


def test_wiring_endpoint_can_switch_to_the_pitakuru_preset():
    client, manager, recorder = make_client()
    body = client.post("/api/wiring", json={"preset": "pitakuru"}).json()
    assert body["preset"] == "pitakuru"
    assert manager.wiring.hwto2 == "jumper"
    recorder.close()


def test_wiring_endpoint_can_drop_the_relay():
    client, manager, recorder = make_client()
    client.post("/api/wiring", json={"preset": "pitakuru"})
    body = client.post("/api/wiring", json={"relay": False}).json()
    assert body["relay"] is False
    assert body["inputs"] == {"hwto1_on": False, "hwto2_on": True}
    manager.step()
    assert manager.models[1].hwto.hwto1_on is False
    recorder.close()


def test_wiring_endpoint_can_set_each_channel_individually():
    client, manager, recorder = make_client()
    body = client.post("/api/wiring", json={"hwto1": "open", "hwto2": "jumper"}).json()
    assert body["hwto1"]["source"] == "open"
    assert body["preset"] is None  # 既知のプリセットに一致しない組み合わせ
    recorder.close()


def test_wiring_endpoint_rejects_an_unknown_source():
    client, _manager, recorder = make_client()
    response = client.post("/api/wiring", json={"hwto1": "battery"})
    assert response.status_code == 400
    assert "battery" in response.json()["detail"]
    recorder.close()


def test_wiring_endpoint_rejects_an_unknown_preset():
    client, _manager, recorder = make_client()
    assert client.post("/api/wiring", json={"preset": "nonsense"}).status_code == 400
    recorder.close()


def test_snapshot_exposes_alarm_names_and_remote_io():
    """Web のアラームモニタ / I/O モニタが表示に必要な情報。"""
    from omsim.driver.model import DriverModel

    model = DriverModel(node_id=1)
    model.step(0.001)
    model.inject_alarm(0x30)
    snapshot = model.snapshot()
    assert snapshot["alarm"] == 0x30
    assert snapshot["alarm_name"] == "Overload"
    assert snapshot["alarm_history_decoded"][0] == {
        "emcy": 0xFF30, "code": 0x30, "name": "Overload"}
    assert "remote_inputs" in snapshot
    assert "remote_outputs" in snapshot
