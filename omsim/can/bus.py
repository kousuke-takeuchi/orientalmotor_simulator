"""SocketCAN への接続。実機の can0 と vcan0 で同じコードが動く。"""
import canopen


def open_network(channel="vcan0", interface="socketcan", bitrate=500000):
    network = canopen.Network()
    network.connect(channel=channel, interface=interface, bitrate=bitrate)
    return network


def close_network(network):
    if network is not None:
        network.disconnect()
