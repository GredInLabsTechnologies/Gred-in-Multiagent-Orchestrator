import socket
from unittest.mock import MagicMock, patch

from scripts.tools import probe_ports


def test_probe_ports_handles_open_port(capsys):
    fake_socket = MagicMock()
    fake_socket.__enter__.return_value = fake_socket

    with patch("socket.socket", return_value=fake_socket):
        probe_ports.probe_ports("127.0.0.1", [1234])

    fake_socket.connect.assert_called_once_with(("127.0.0.1", 1234))
    captured = capsys.readouterr()
    assert "Port 1234 is OPEN" in captured.out


def test_probe_ports_swallows_socket_errors():
    fake_socket = MagicMock()
    fake_socket.__enter__.return_value = fake_socket
    fake_socket.connect.side_effect = socket.timeout()

    with patch("socket.socket", return_value=fake_socket):
        probe_ports.probe_ports("127.0.0.1", [4321])

    fake_socket.connect.assert_called_once_with(("127.0.0.1", 4321))
