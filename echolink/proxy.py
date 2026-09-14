"""
EchoLink proxy client — HTTP + WebSocket via webapp.echolink.org.

All EchoLink operations (login, connect, audio) go through the official
EchoLink web app backend at webapp.echolink.org/ProxyServlet (JSON POST)
and wss://webapp.echolink.org/websocket/{proxyHandle} (binary audio frames).

WebSocket audio frame format (both directions):
  Sending:   [Int16LE: 1 (type=audio)] [Int16LE samples...]
  Receiving: [byte: type (1=audio)]    [byte: padding] [Int16LE samples...]
"""

import asyncio
import struct
from collections import deque

import aiohttp

PROXY_URL = "https://webapp.echolink.org/ProxyServlet"
WS_URL_TEMPLATE = "wss://webapp.echolink.org/websocket/{}"

AUDIO_TYPE = 1
CHAT_TYPE = 2
SYSTEM_TYPE = 4

SAMPLES_PER_PACKET = 640  # 80ms at 8kHz
SAMPLE_RATE = 8000

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EchoLink-MCP)",
    "Origin": "https://webapp.echolink.org",
    "Referer": "https://webapp.echolink.org/",
}


class EchoLinkProxy:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._proxy_handle: str | None = None
        self._rx_buffer: deque[bytes] = deque()  # raw Int16LE sample bytes
        self._rx_task: asyncio.Task | None = None
        self._connected_callsign: str | None = None

    @property
    def is_logged_in(self) -> bool:
        return self._proxy_handle is not None

    @property
    def is_connected(self) -> bool:
        return self._connected_callsign is not None

    @property
    def connected_callsign(self) -> str | None:
        return self._connected_callsign

    async def login(self, callsign: str, password: str) -> dict:
        """Authenticate with EchoLink. Returns API response dict."""
        if not self._session:
            self._session = aiohttp.ClientSession(headers=_HEADERS)

        result = await self._api("login", {
            "callsign": callsign.upper(),
            "password": password,
            "location": "AI Station",
            "busy": False,
            "bigEndian": False,
            "softwareVersion": "1.3.6",
        })

        if result.get("success"):
            self._proxy_handle = result["proxyHandle"]
            # Open WebSocket immediately after login (required before any connect call)
            ws_url = WS_URL_TEMPLATE.format(self._proxy_handle)
            self._ws = await self._session.ws_connect(ws_url, heartbeat=20)
            self._rx_task = asyncio.create_task(self._receive_loop())
            # Declare audio format to proxy
            await self._api("setClientParams", {
                "proxyHandle": self._proxy_handle,
                "playbackSampleRate": 8000,
                "recordSampleRate": 8000,
                "playbackEncoding": "PCM",
            })
        return result

    async def connect(self, remote_callsign: str) -> dict:
        """Connect to a remote EchoLink station and open the audio WebSocket."""
        if not self.is_logged_in:
            raise RuntimeError("Call login() first")

        result = await self._api("connect", {
            "remoteCallsign": remote_callsign.upper(),
            "myName": "webapp.echolink.org",
            "proxyHandle": self._proxy_handle,
            "acceptingIncoming": False,
        })

        if result.get("success"):
            self._connected_callsign = remote_callsign.upper()
            self._rx_buffer.clear()

        return result

    async def disconnect(self) -> dict:
        """Disconnect from the current station (WebSocket stays open for re-use)."""
        self._connected_callsign = None
        self._rx_buffer.clear()

        result = {}
        if self.is_logged_in:
            result = await self._api("disconnect", {
                "sendBye": True,
                "proxyHandle": self._proxy_handle,
            })
        return result

    async def logout(self) -> dict:
        """Log out and release resources."""
        await self.disconnect()

        if self._rx_task:
            self._rx_task.cancel()
            self._rx_task = None

        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None

        result = {}
        if self.is_logged_in:
            result = await self._api("logout", {"proxyHandle": self._proxy_handle})
        self._proxy_handle = None

        if self._session:
            await self._session.close()
            self._session = None

        return result

    async def get_station_list(self) -> list[dict]:
        """Return all currently online EchoLink stations."""
        if not self.is_logged_in:
            raise RuntimeError("Call login() first")

        result = await self._api("getStationList", {"proxyHandle": self._proxy_handle})

        if not result.get("success"):
            return []

        stations = []
        # Response: {"structured": [{"Category": [station, ...]}, ...]}
        # Each station is a dict with callsign/location/nodeNum, OR a plain string callsign.
        for category_item in result.get("structured", []):
            for cat_name, entries in category_item.items():
                if isinstance(entries, str):
                    # e.g. {"Test Server": "*ECHOTEST*"}
                    stations.append({
                        "callsign": entries,
                        "location": cat_name,
                        "status": "online",
                        "node_number": "",
                    })
                elif isinstance(entries, list):
                    for s in entries:
                        if isinstance(s, dict) and s.get("callsign"):
                            stations.append({
                                "callsign": s.get("callsign", ""),
                                "location": s.get("location", ""),
                                "status": s.get("status", "online"),
                                "node_number": s.get("nodeNum", ""),
                            })
        return stations

    async def find_station(self, query: str) -> list[dict]:
        """Search online stations by callsign prefix or node number."""
        all_stations = await self.get_station_list()
        q = query.upper().strip("*")
        return [
            s for s in all_stations
            if q in s.get("callsign", "").upper().strip("*")
            or str(s.get("node_number", "")) == q
        ]

    async def send_pcm(self, pcm_bytes: bytes) -> None:
        """
        Send 8kHz 16-bit mono PCM audio over the WebSocket connection.
        Audio is chunked into SAMPLES_PER_PACKET (640) sample frames.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to any station")

        num_samples = len(pcm_bytes) // 2
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes)

        for i in range(0, num_samples, SAMPLES_PER_PACKET):
            chunk = samples[i:i + SAMPLES_PER_PACKET]
            # Pad last chunk to SAMPLES_PER_PACKET if needed
            if len(chunk) < SAMPLES_PER_PACKET:
                chunk = chunk + (0,) * (SAMPLES_PER_PACKET - len(chunk))
            # Frame: [Int16LE: 1 (audio type)] [640 Int16LE samples]
            frame = struct.pack(f"<h{SAMPLES_PER_PACKET}h", 1, *chunk)
            await self._ws.send_bytes(frame)
            # Pace to real-time: 640 samples / 8000 Hz = 80ms
            await asyncio.sleep(SAMPLES_PER_PACKET / SAMPLE_RATE)

    async def receive_pcm(self, timeout: float = 5.0) -> bytes:
        """
        Collect received audio for `timeout` seconds and return raw 8kHz PCM bytes.
        Returns empty bytes if nothing was received.
        """
        self._rx_buffer.clear()
        await asyncio.sleep(timeout)

        if not self._rx_buffer:
            return b""
        return b"".join(self._rx_buffer)

    async def _receive_loop(self) -> None:
        """Background task: read WebSocket frames and buffer audio payloads."""
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    data: bytes = msg.data
                    if len(data) >= 3 and data[0] == AUDIO_TYPE:
                        # Bytes 2+ are Int16LE PCM samples
                        self._rx_buffer.append(data[2:])
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        except asyncio.CancelledError:
            pass

    async def _api(self, method: str, params: dict) -> dict:
        """POST to ProxyServlet with the given method and params."""
        if not self._session:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        body = {"method": method, **params}
        async with self._session.post(
            PROXY_URL,
            json=body,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            return await resp.json()
