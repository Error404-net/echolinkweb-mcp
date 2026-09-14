# EchoLink MCP Server

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-4DE1FF)
![License: MIT](https://img.shields.io/badge/license-MIT-37F0A6)

Bridge between EchoLink (amateur radio VoIP) and AI voice models via the [Model Context Protocol](https://modelcontextprotocol.io).

An AI can connect to the EchoLink network, transmit speech (TTS), and receive/transcribe audio (STT) — enabling fully automated radio conversations.

## Requirements

- **Licensed amateur radio callsign** with an EchoLink account — [register at echolink.org](https://www.echolink.org/registration.jsp)
- Python 3.12+
- ffmpeg (for GSM-FR audio codec)
- An API key for your chosen TTS/STT backend (default: OpenAI)

```
brew install ffmpeg        # macOS
sudo apt install ffmpeg    # Linux
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your callsign, password, and API keys
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
| `TTS_VOICE` | No | `alloy` | Voice name for TTS |
| `ECHOLINK_SERVER` | No | `naeast.echolink.org` | Directory server |
| `ECHOLINK_PORT` | No | `5200` | Directory server port |

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
      "command": "python",
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
claude mcp add echolink -- python /path/to/echolinkweb-mcp/server.py
```

Then set credentials:
```bash
export ECHOLINK_CALLSIGN=W6ABC
export ECHOLINK_PASSWORD=your_password
export OPENAI_API_KEY=sk-...
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `find_node(query)` | Search EchoLink directory by callsign or node number |
| `connect(node_number)` | Connect to a node (use 9999 for EchoTest) |
| `disconnect()` | Disconnect from current node |
| `say(text)` | TTS → transmit speech on the radio |
| `listen(timeout_seconds)` | Receive audio → STT → return transcription |
| `status()` | Current connection state |

## Testing with EchoTest

EchoTest (node 9999) is the official EchoLink loopback — it records your transmission and plays it back. Use it to verify the full audio pipeline without connecting to a live station.

Example AI conversation flow:
```
find_node("9999")          → confirms EchoTest is available
connect(9999)              → establishes audio link
say("Hello, EchoTest")     → TTS synthesized and transmitted
listen(12)                 → waits for echo, returns transcription
disconnect()               → closes the link
```

## Audio Pipeline

```
AI text → TTS backend → MP3/PCM → resample 8kHz → GSM-FR encode → RTP/UDP → EchoLink
EchoLink → RTP/UDP → GSM-FR decode → PCM 8kHz → WAV → STT backend → AI text
```

**Codec**: GSM-FR (GSM 06.10, 13.2 kbit/s) via ffmpeg — the native EchoLink codec.  
**Network**: UDP port 5198, bidirectional peer-to-peer.  
**Authentication**: TCP challenge-response with MD5 to EchoLink directory server.

## Protocol Notes

The EchoLink protocol is not officially documented by the EchoLink organization. This implementation is based on:
- [SvxLink EchoLink Proxy Protocol](http://www.svxlink.org/doc/echolink_proxy_protocol.html)
- [MicroLink](https://github.com/brucemack/microlink) — C++ open-source implementation
- [OpenELP](https://github.com/cottsay/openelp) — open-source EchoLink proxy

Some packet formats (particularly the connection handshake) are marked with `# ponytail: verify` comments in the source and may need adjustment after testing against a live EchoLink connection. File an issue or PR if you capture the correct format.

## Directory Server Compatibility

The node list parsing in `echolink/directory.py` (`_parse_node_list`) is a best-effort CSV parser against the echolink.org response format. If the format differs from what's expected, update the parser and open a PR with the actual response sample.

## License

MIT. Ham radio, keep the spirit of sharing.

---

Built by [ERROR404.NET](https://error404.net).
`!ignore → return "404: Message not found"`
