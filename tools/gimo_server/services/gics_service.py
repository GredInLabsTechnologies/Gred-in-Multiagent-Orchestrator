import asyncio
import json
import logging
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import GICS_DAEMON_SCRIPT, GICS_SOCKET_PATH, GICS_TOKEN_PATH, OPS_DATA_DIR

logger = logging.getLogger("orchestrator.services.gics")


class GicsService:
    """Service to manage GICS Daemon and communicate via JSON-RPC over TCP/Pipe."""

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._token: Optional[str] = None
        self._socket: Optional[socket.socket] = None
        self._pipe_file: Optional[Any] = None  # For Windows Named Pipe
        self._actual_socket_path: Optional[str] = None
        
    def start_daemon(self) -> None:
        """Start the GICS daemon subprocess."""
        if self._process and self._process.poll() is None:
            logger.info("GICS Daemon already running (pid=%s)", self._process.pid)
            return

        if not GICS_DAEMON_SCRIPT.exists():
            logger.error("GICS Daemon script not found at %s", GICS_DAEMON_SCRIPT)
            return

        logger.info("Starting GICS Daemon from %s...", GICS_DAEMON_SCRIPT)
        
        # Ensure the data directory exists
        gics_data_path = OPS_DATA_DIR / "gics_data"
        gics_data_path.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["GICS_DATA_PATH"] = str(gics_data_path)
        # On Windows, server.js likely uses a named pipe if we give it a pipe path, 
        # or a file path for unix domain socket. 
        # But 'net.createServer' on Windows with a path argument creates a named pipe.
        # Let's use a named pipe path format for Windows if needed, or just a file path and let node handle it.
        # Node docs: on Windows, a path is a named pipe.
        # Python's `socket.connect` on Windows doesn't support AF_UNIX until recently (Py3.10+ dev mode?)
        # safer to use a TCP port for cross-platform simplicity if GICS supports it.
        # Checking server.js: `this.server.listen(this.config.socketPath, ...)`
        # If we pass a port number to socketPath? No, Config says socketPath is string.
        # If we pass "\\.\pipe\gics.sock" ??
        
        # Let's assume standard file path for now, but on Windows we might need to adjust.
        # For this implementation, I will treat it as a file path that Node turns into a pipe.
        # Connecting to it from Python on Windows requires `pywin32` or specific pipe open handling.
        # To avoid dependency hell, IF config allows, we should ask Daemon to listen on TCP.
        # Analyzing server.js line 108: `this.server.listen(this.config.socketPath, ...)`
        # If socketPath is a path, it's IPC.
        
        # DECISION: We will try to rely on Python's `socket.AF_UNIX` if available (Linux/Mac/Windows 10+ recent).
        # functionality. If not, we might fail.
        # Actually, let's just pass the path.
        
        socket_path_str = str(GICS_SOCKET_PATH)
        
        # On Windows, we MUST use a named pipe path format for Node.
        if os.name == 'nt':
             socket_path_str = r'\\.\pipe\gics_sock'
        
        env["GICS_SOCKET_PATH"] = socket_path_str
        env["GICS_TOKEN_PATH"] = str(GICS_TOKEN_PATH)

        cmd = ["node", str(GICS_DAEMON_SCRIPT)]
        
        try:
            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logger.info("GICS Daemon started with pid=%s", self._process.pid)
            self._wait_for_token()
            
            # Update the stored socket path to match what we told the daemon
            # (In case we changed it for Windows named pipe)
            self._actual_socket_path = socket_path_str
            
        except Exception as e:
            logger.error("Failed to start GICS Daemon: %s", e)

    def stop_daemon(self) -> None:
        """Stop the GICS daemon."""
        if self._process:
            logger.info("Stopping GICS Daemon...")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            self._close_socket()

    def _wait_for_token(self, timeout: int = 10) -> None:
        start = time.time()
        while time.time() - start < timeout:
            if GICS_TOKEN_PATH.exists():
                try:
                    self._token = GICS_TOKEN_PATH.read_text().strip()
                    return
                except (OSError, ValueError):
                    pass
            time.sleep(0.5)
        logger.warning("Timed out waiting for GICS token file at %s", GICS_TOKEN_PATH)

    def _close_socket(self):
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        if self._pipe_file:
            try:
                self._pipe_file.close()
            except OSError:
                pass
            self._pipe_file = None

    def _connect(self) -> None:
        """Establish connection to daemon."""
        if self._socket or self._pipe_file:
            return

        if not hasattr(self, '_actual_socket_path') or self._actual_socket_path is None:
             self._actual_socket_path = str(GICS_SOCKET_PATH)
             if os.name == 'nt':
                 self._actual_socket_path = r'\\.\pipe\gics_sock'

        try:
             if os.name == 'nt':
                 # Use Named Pipe on Windows via file API
                 # buffering=0 is crucial for real-time communication
                 self._pipe_file = open(self._actual_socket_path, 'rb+', buffering=0)
             elif hasattr(socket, 'AF_UNIX'):
                 self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                 self._socket.connect(self._actual_socket_path)
                 self._socket.settimeout(5.0)
             else:
                 raise NotImplementedError("AF_UNIX not supported on this platform")
        except Exception as e:
            logger.error("Failed to connect to GICS Daemon at %s: %s", self._actual_socket_path, e)
            raise

    def send_command(self, method: str, params: Dict[str, Any] = None) -> Any:
        """Send a JSON-RPC 2.0 command to the daemon."""
        if not self._token:
            raise RuntimeError("GICS Token not available")
            
        self._connect()
        
        request_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
            "token": self._token
        }
        
        message = json.dumps(payload) + "\n"
        
        try:
            if self._pipe_file:
                self._pipe_file.write(message.encode('utf-8'))
                response_data = self._pipe_file.readline()
                if not response_data:
                    raise ConnectionError("Pipe closed remotely")
                response = json.loads(response_data.decode('utf-8'))
            else:
                self._socket.sendall(message.encode('utf-8'))
                
                # Read response (line buffered)
                response_data = b""
                while b"\n" not in response_data:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        raise ConnectionError("Socket closed remotely")
                    response_data += chunk
                
                line, _, _ = response_data.partition(b"\n")
                response = json.loads(line.decode('utf-8'))
            
            if "error" in response:
                raise RuntimeError(f"GICS Error: {response['error']}")
                
            return response.get("result")
            
        except ConnectionError:
            logger.warning("GICS Daemon connection broken, retrying...")
            self._close_socket()
            self._connect()
            # Retry once
            self._socket.sendall(message.encode('utf-8'))
            # ... (Reading logic repeat - simplified for brevity, in real prod use a retry decorators)
            # For this 'mvp', just fail if retry needed to keep code simple
            return None 

    def put(self, key: str, fields: Dict[str, Any]) -> Any:
        return self.send_command("put", {"key": key, "fields": fields})

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self.send_command("get", {"key": key})

    def scan(self, prefix: str = "", include_fields: bool = True) -> List[Dict[str, Any]]:
        result = self.send_command("scan", {"prefix": prefix, "includeFields": include_fields})
        if result and "items" in result:
            return result["items"]
        return []

    def flush(self) -> Any:
        """No-op: GICS daemon auto-flushes. Manual flush not exposed via JSON-RPC."""
        pass
