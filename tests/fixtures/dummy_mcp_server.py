import sys
import json
import logging

# Configure logging to stderr to avoid interfering with stdout JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("dummy_mcp_server")

def main():
    logger.info("Dummy MCP Server started")
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
                
            line = line.strip()
            if not line:
                continue
                
            logger.info(f"Received: {line}")
            request = json.loads(line)
            
            response = handle_request(request)
            if response:
                print(json.dumps(response))
                sys.stdout.flush()
                logger.info(f"Sent: {json.dumps(response)}")
                
        except Exception as e:
            logger.error(f"Error processing loop: {e}")
            break

def handle_request(request):
    method = request.get("method")
    req_id = request.get("id")
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "0.1.0",
                "capabilities": {},
                "serverInfo": {"name": "dummy-mcp", "version": "1.0"}
            }
        }
        
    if method == "notifications/initialized":
        return None
        
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echoes back the input",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "message": {"type": "string"}
                            },
                            "required": ["message"]
                        }
                    },
                    {
                        "name": "add",
                        "description": "Adds two numbers",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "a": {"type": "number"},
                                "b": {"type": "number"}
                            },
                            "required": ["a", "b"]
                        }
                    }
                ]
            }
        }
        
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        
        if name == "echo":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Echo: {args.get('message')}"}]
                }
            }
            
        if name == "add":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(args.get("a", 0) + args.get("b", 0))}]
                }
            }
            
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": "Method not found"}
    }

if __name__ == "__main__":
    main()
