"""canopen.LocalNode のコールバックを DriverModel に繋ぐ。"""
import canopen

from omsim.driver.errors import ObjectAccessError


def build_local_node(node_id, od, model):
    node = canopen.LocalNode(node_id, od)

    def on_read(index, subindex, od):
        try:
            return model.read_object(index, subindex)
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    def on_write(index, subindex, od, data):
        try:
            model.write_object(index, subindex, od.decode_raw(data))
        except ObjectAccessError as err:
            raise canopen.SdoAbortedError(err.abort_code)

    node.add_read_callback(on_read)
    node.add_write_callback(on_write)
    node.driver_model = model
    return node
