"""
HTTP/SSE server mode — for Pneum.ai (and other remote MCP clients).

Exposes all EchoLink MCP tools over SSE at:
  http://HOST:PORT/sse

Usage:
    python run_http.py [--port 8765] [--host 0.0.0.0]

Register in Pneum.ai → Tools Studio → Custom Tools → MCP Tool:
    Server URL: http://<your-ip>:8765/sse
    Tool name:  connect  (or say, listen, transmit_audio, etc.)
"""

import argparse
import os
from dotenv import load_dotenv

load_dotenv()

# Import after env is loaded so tools pick up credentials
import server  # noqa: E402  — registers all @mcp.tool() decorators

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8765")))
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "0.0.0.0"))
    args = parser.parse_args()

    print(f"EchoLink MCP  →  http://{args.host}:{args.port}/sse")
    print(f"Callsign: {os.getenv('ECHOLINK_CALLSIGN', '(not set)')}")
    print(f"TTS: {os.getenv('TTS_BACKEND', 'openai')}  STT: {os.getenv('STT_BACKEND', 'openai')}")
    print()

    server.mcp.run(
        transport="sse",
        host=args.host,
        port=args.port,
    )
