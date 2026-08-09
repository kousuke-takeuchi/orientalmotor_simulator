"""canopen.LocalNode のコールバックを DriverModel に繋ぐ。"""
import canopen

from omsim.driver.errors import ObjectAccessError


def build_local_node(node_id, od, model, queue=None):
    node = canopen.LocalNode(node_id, od)

    def on_read(index, subindex, od):
        try:
            return model.read_object(index, subindex)
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    def on_write(index, subindex, od, data):
        value = od.decode_raw(data)
        if queue is not None:
            # 受信スレッドから直接 model を触らない。適用は step() の先頭。
            queue.put(index, subindex, value)
            return
        try:
            model.write_object(index, subindex, value)
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    node.add_read_callback(on_read)
    node.add_write_callback(on_write)
    node.driver_model = model
    return node


def boot_local_node(node):
    """実機と同様、初期化完了後に boot-up メッセージを送出して PRE-OPERATIONAL へ入る。

    CiA301 4.3 (NMT boot-up) では、スレーブは初期化完了時に COB-ID
    0x700+node_id・データ 1 バイト 0x00 の boot-up メッセージを送出したうえで
    PRE-OPERATIONAL に遷移する。canopen ライブラリの NmtSlave.send_command() は
    内部状態が INITIALISING（0）に遷移した瞬間にのみこの送出を行うため、
    node.nmt.state への直接代入ではバイパスされ、フレームが一切出ない。

    そのため、リセットコマンド（0x81）で一度 INITIALISING を経由させてから
    PRE-OPERATIONAL コマンド（0x80）で遷移させる、実機と同じ 2 段階の手順を踏む。

    呼び出しは、対象の node が Network に登録（network[node.id] = node）された
    後である必要がある。登録前は送信先が無く、フレームを出せない。
    """
    node.nmt.send_command(0x81)  # reset node: INITIALISING を経由し boot-up を送出
    node.nmt.send_command(0x80)  # PRE-OPERATIONAL へ遷移（ハートビートもここで開始）
