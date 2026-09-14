"""
EchoLink MCP Server

Bridges the EchoLink amateur radio network with AI voice models via MCP.
Uses webapp.echolink.org backend (JSON API + WebSocket) — no raw protocol needed.

Run:
    mcp dev server.py          # development inspector
    mcp run server.py          # production stdio
"""

import asyncio
import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from echolink.proxy import EchoLinkProxy
from audio.pipeline import text_to_pcm, pcm_to_text

load_dotenv()

mcp = FastMCP(
    name="EchoLink",
    instructions=(
        "Control an EchoLink amateur radio node. "
        "Use find_station to search for stations, connect to link up, "
        "say to transmit speech, and listen to receive/transcribe audio. "
        "EchoTest (*ECHOTEST*) echoes your audio back — use it for testing. "
        "Requires ECHOLINK_CALLSIGN and ECHOLINK_PASSWORD in environment."
    ),
)

# One proxy connection per MCP session
_proxy = EchoLinkProxy()


def _require_creds() -> tuple[str, str]:
    cs = os.getenv("ECHOLINK_CALLSIGN", "").strip().upper()
    pw = os.getenv("ECHOLINK_PASSWORD", "").strip()
    if not cs or not pw:
        raise RuntimeError(
            "ECHOLINK_CALLSIGN and ECHOLINK_PASSWORD must be set. See .env.example"
        )
    return cs, pw


async def _ensure_logged_in() -> None:
    if not _proxy.is_logged_in:
        cs, pw = _require_creds()
        result = await _proxy.login(cs, pw)
        if not result.get("success"):
            raise RuntimeError(
                f"EchoLink login failed: {result.get('error') or result.get('message')}"
            )


@mcp.tool()
async def find_station(query: str) -> list[dict]:
    """
    Search for online EchoLink stations by callsign or node number.

    Args:
        query: Callsign prefix or full callsign (e.g. "W6", "K5ABC", "*ECHOTEST*")

    Returns a list with callsign, location, status, and node_number.
    Special stations: *ECHOTEST* (loopback), *WWROF* (conference), *EL-RUSSIA* etc.
    """
    await _ensure_logged_in()
    return await _proxy.find_station(query)


@mcp.tool()
async def connect(callsign: str) -> str:
    """
    Connect to an EchoLink station.

    Args:
        callsign: Station callsign (e.g. "*ECHOTEST*", "W6ABC-R", "K5XYZ-L")

    Use *ECHOTEST* for a safe loopback test — it records your audio and plays it back.
    """
    if _proxy.is_connected:
        return f"Already connected to {_proxy.connected_callsign}. Call disconnect() first."

    await _ensure_logged_in()
    result = await _proxy.connect(callsign)

    if result.get("success"):
        peer = result.get("peerName") or callsign
        addr = result.get("peerAddress", "")
        return f"Connected to {peer}" + (f" ({addr})" if addr else "")

    return f"Connection failed: {result.get('error') or result.get('message', 'unknown error')}"


@mcp.tool()
async def disconnect() -> str:
    """Disconnect from the current EchoLink station."""
    if not _proxy.is_connected:
        return "Not connected."
    node = _proxy.connected_callsign
    await _proxy.disconnect()
    return f"Disconnected from {node}."


@mcp.tool()
async def say(text: str) -> str:
    """
    Convert text to speech and transmit it over the EchoLink connection.

    The text is synthesized via the configured TTS backend (TTS_BACKEND env var,
    default: openai), converted to 8kHz PCM, and streamed to the connected station.

    Args:
        text: Words to speak on the radio
    """
    if not _proxy.is_connected:
        return "Not connected. Call connect() first."
    if not text.strip():
        return "Nothing to say."

    pcm = await text_to_pcm(text)
    await _proxy.send_pcm(pcm)
    duration_s = len(pcm) / (8000 * 2)
    return f"Transmitted {duration_s:.1f}s: {text!r}"


@mcp.tool()
async def listen(timeout_seconds: float = 8.0) -> str:
    """
    Receive audio from the connected station and return the transcription.

    Collects audio for `timeout_seconds`, then transcribes with the configured
    STT backend (STT_BACKEND env var, default: openai).

    Args:
        timeout_seconds: How long to listen (default 8.0). Use 10-12 for EchoTest
                         since it plays back after your transmission ends.
    """
    if not _proxy.is_connected:
        return "Not connected. Call connect() first."

    pcm = await _proxy.receive_pcm(timeout=timeout_seconds)
    if not pcm:
        return "(no audio received)"

    text = await pcm_to_text(pcm)
    return text or "(audio received but transcription was empty)"


@mcp.tool()
async def status() -> dict:
    """Return current connection and configuration status."""
    return {
        "logged_in": _proxy.is_logged_in,
        "connected": _proxy.is_connected,
        "connected_to": _proxy.connected_callsign,
        "callsign": os.getenv("ECHOLINK_CALLSIGN", "(not set)"),
        "tts_backend": os.getenv("TTS_BACKEND", "openai"),
        "stt_backend": os.getenv("STT_BACKEND", "openai"),
    }
