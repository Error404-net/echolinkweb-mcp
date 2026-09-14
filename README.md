# EchoLink MCP Server

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-4DE1FF)
![License: MIT](https://img.shields.io/badge/license-MIT-37F0A6)

Bridge between EchoLink (amateur radio VoIP) and AI voice models via the [Model Context Protocol](https://modelcontextprotocol.io).

An AI can connect to the EchoLink network, transmit speech (TTS), and receive/transcribe audio (STT) — enabling fully automated radio conversations.

## Requirements

- **Licensed amateur radio callsign** with an EchoLink account — [register at echolink.org](https://www.echolink.org/registration.jsp)
- Python 3.12+
- ffmpeg
- An API key for your TTS/STT backend (default: OpenAI)

## Setup

### Linux (Ubuntu/Debian server)

```bash
# System dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv ffmpeg git

# Clone and install
git clone https://github.com/yourusername/echolinkweb-mcp.git
cd echolinkweb-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
nano .env   # fill in ECHOLINK_CALLSIGN, ECHOLINK_PASSWORD, OPENAI_API_KEY
```

### macOS

```bash
brew install ffmpeg python@3.12 git
git clone https://github.com/yourusername/echolinkweb-mcp.git
cd echolinkweb-mcp
pip3 install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

All credentials are environment variables — never hardcoded.

| Variable | Required | Default | Description |
|---|---|---|---|
| `ECHOLINK_CALLSIGN` | Yes | — | Your licensed callsign (e.g. `W6ABC`) |
| `ECHOLINK_PASSWORD` | Yes | — | Your EchoLink account password |
| `TTS_BACKEND` | No | `openai` | `openai` \| `elevenlabs` \| `kokoro` |
| `STT_BACKEND` | No | `openai` | `openai` \| `whisper_local` |
| `OPENAI_API_KEY` | If using openai | — | OpenAI API key |
| `ELEVENLABS_API_KEY` | If TTS=elevenlabs | — | ElevenLabs key |
| `TTS_VOICE` | No | `alloy` | Voice name for TTS (OpenAI: alloy, echo, fable, onyx, nova, shimmer) |
| `MCP_PORT` | No | `8765` | Port for HTTP/SSE server (`run_http.py`) |
| `MCP_HOST` | No | `0.0.0.0` | Bind host for HTTP/SSE server |

## Running

### Development (with inspector UI)

```bash
mcp dev server.py
```

### With Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "echolink": {
      "command": "python3",
      "args": ["/path/to/echolinkweb-mcp/server.py"],
      "env": {
        "ECHOLINK_CALLSIGN": "W6ABC",
        "ECHOLINK_PASSWORD": "your_password",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

### With Claude Code

```bash
claude mcp add echolink -- python3 /path/to/echolinkweb-mcp/server.py
```

Then set credentials:
```bash
export ECHOLINK_CALLSIGN=W6ABC
export ECHOLINK_PASSWORD=your_password
export OPENAI_API_KEY=sk-...
```

### Pneum.ai (HTTP/SSE mode)

This is the recommended path for running EchoLink via a voice AI agent. The MCP server runs as an HTTP service that Pneum.ai connects to remotely.

**Step 1 — Start the HTTP server on your Linux/Mac machine:**

```bash
# If using a venv (Linux):
source .venv/bin/activate

python3 run_http.py
# Starts on http://0.0.0.0:8765/sse by default
# Custom port: python3 run_http.py --port 9000
```

Find your server's IP with `hostname -I` (Linux) or `ipconfig getifaddr en0` (macOS). The MCP endpoint is:

```
http://YOUR_SERVER_IP:8765/sse
```

If running on a remote/cloud server, make sure port 8765 is open in your firewall/security group.

**Step 2 — Register in Pneum.ai Tools Studio (Part A: agent control):**

1. Open [Pneum.ai](https://pneum.ai) → **Tools Studio → Custom Tools → MCP Tool**
2. Set **Server URL** to `http://YOUR_SERVER_IP:8765/sse`
3. Enable these tools: `connect`, `say`, `transmit_audio`, `listen`, `disconnect`, `find_station`, `status`
4. Save — your Pneum.ai agent can now search EchoLink stations, connect, and talk on air

**Step 3 — Use Pneum.ai's own voice on air (Part B: bypass `say`):**

If you want Pneum.ai's Voice Studio voice to be what goes out over the radio (instead of OpenAI/ElevenLabs), instruct the agent to use `transmit_audio` instead of `say`:

1. Pneum.ai synthesizes speech with its voice engine
2. Base64-encodes the audio
3. Calls `transmit_audio(audio_base64=..., format="wav")` — that audio plays live on the radio

This gives you Pneum.ai's voice directly on EchoLink with no second TTS round-trip. Both `say` (text-in) and `transmit_audio` (audio-in) are available — the agent can choose per-transmission.

## MCP Tools

| Tool | Description |
|------|-------------|
| `find_station(query)` | Search online EchoLink stations by callsign prefix |
| `connect(callsign)` | Connect to a station (e.g. `*ECHOTEST*` for loopback test) |
| `disconnect()` | Disconnect from current station |
| `say(text)` | TTS → transmit speech on the radio |
| `transmit_audio(audio_base64, format)` | Send pre-synthesized audio directly (wav/mp3/pcm_8k) |
| `listen(timeout_seconds)` | Receive audio → STT → return transcription |
| `status()` | Current connection and config state |

## Testing with EchoTest

`*ECHOTEST*` is the official EchoLink loopback node — it records your transmission and plays it back. Use it to verify the full audio pipeline without connecting to a live station.

```
find_station("ECHOTEST")   → confirm it's online
connect("*ECHOTEST*")      → establish link
say("Hello EchoTest")      → TTS synthesized and transmitted
listen(12)                 → wait for echo, returns transcription
disconnect()               → close the link
```

## Architecture

```
AI ──MCP tools──► server.py (FastMCP)
                       │
               echolink/proxy.py
               (JSON API + WebSocket)
                       │
         webapp.echolink.org/ProxyServlet
                       │
              EchoLink network
```

**Auth & control**: `POST https://webapp.echolink.org/ProxyServlet` (JSON)  
**Audio**: `wss://webapp.echolink.org/websocket/{proxyHandle}` (binary PCM frames)  
**No raw EchoLink protocol needed** — the webapp backend handles authentication, NAT traversal, and codec conversion server-side.

**Audio pipeline**:
- Outgoing: `say(text)` → TTS API → MP3 → ffmpeg → 8kHz PCM → WebSocket → EchoLink
- Incoming: EchoLink → WebSocket → 8kHz PCM → WAV → STT API → text

## License

MIT. Ham radio, keep the spirit of sharing.

---

Built by [ERROR404.NET](https://error404.net).
