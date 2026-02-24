import sys
import json

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            request = json.loads(line)
            method = request.get("method")
            req_id = request.get("id")
            
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "0.1.0",
                        "capabilities": {},
                        "serverInfo": {"name": "test-mcp", "version": "1.0"}
                    }
                }
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {"name": "real_t1", "description": "Test tool", "inputSchema": {"type": "object"}}
                        ]
                    }
                }
            elif method == "tools/call":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "result": "hi\n",
                        "content": [{"type": "text", "text": "hi\n"}]
                    }
                }
            elif method == "notifications/initialized":
                continue
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": "Method not found"}
                }
            
            print(json.dumps(response))
            sys.stdout.flush()
        except:
            break

if __name__ == "__main__":
    main()
