import socket


def probe_ports(host, ports):
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.connect((host, port))
                print(f"Port {port} is OPEN")
            except OSError:
                pass


if __name__ == "__main__":
    host = "127.0.0.1"
    ports = [1234, 1235, 1236, 1237, 5000, 5001, 8080, 11434]
    probe_ports(host, ports)
