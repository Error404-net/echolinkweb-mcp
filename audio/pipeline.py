"""
TTS/STT pipeline with pluggable backends.

TTS_BACKEND: openai (default) | elevenlabs | kokoro
STT_BACKEND: openai (default) | whisper_local

All functions work with 8kHz mono 16-bit PCM (EchoLink's native format).
"""

import io
import os
import tempfile

from echolink.codec import mp3_to_pcm_8k


TTS_BACKEND = os.getenv("TTS_BACKEND", "openai").lower()
STT_BACKEND = os.getenv("STT_BACKEND", "openai").lower()
TTS_VOICE = os.getenv("TTS_VOICE", "alloy")


async def text_to_pcm(text: str) -> bytes:
    """Convert text to 8kHz mono 16-bit PCM for EchoLink transmission."""
    if TTS_BACKEND == "openai":
        return await _tts_openai(text)
    elif TTS_BACKEND == "elevenlabs":
        return await _tts_elevenlabs(text)
    elif TTS_BACKEND == "kokoro":
        return await _tts_kokoro(text)
    raise ValueError(f"Unknown TTS_BACKEND: {TTS_BACKEND!r}")


async def pcm_to_text(pcm_bytes: bytes) -> str:
    """Transcribe 8kHz PCM audio to text."""
    if STT_BACKEND == "openai":
        return await _stt_openai(pcm_bytes)
    elif STT_BACKEND == "whisper_local":
        return await _stt_whisper_local(pcm_bytes)
    raise ValueError(f"Unknown STT_BACKEND: {STT_BACKEND!r}")


# --- TTS backends ---

async def _tts_openai(text: str) -> bytes:
    from openai import AsyncOpenAI
    client = AsyncOpenAI()
    response = await client.audio.speech.create(
        model="tts-1",
        voice=TTS_VOICE,
        input=text,
        response_format="mp3",
    )
    mp3_bytes = await response.aread()
    return mp3_to_pcm_8k(mp3_bytes)


async def _tts_elevenlabs(text: str) -> bytes:
    import aiohttp
    api_key = os.environ["ELEVENLABS_API_KEY"]
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # default: Rachel
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={"text": text, "model_id": "eleven_monolingual_v1"},
        ) as resp:
            resp.raise_for_status()
            mp3_bytes = await resp.read()
    return mp3_to_pcm_8k(mp3_bytes)


async def _tts_kokoro(text: str) -> bytes:
    """
    Local Kokoro TTS (https://github.com/hexgrad/kokoro).
    Requires: pip install kokoro soundfile
    # ponytail: only wire if kokoro is installed; keeps dependency optional
    """
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _kokoro_sync, text)
    except ImportError:
        raise RuntimeError("kokoro not installed. Run: pip install kokoro soundfile")


def _kokoro_sync(text: str) -> bytes:
    from kokoro import KPipeline
    import numpy as np
    import struct
    pipeline = KPipeline(lang_code="a")
    samples = []
    for _, _, audio in pipeline(text, voice="af_heart"):
        samples.append(audio)
    combined = np.concatenate(samples)
    # Kokoro outputs 24kHz; resample to 8kHz
    pcm_24k = (combined * 32767).astype(np.int16).tobytes()
    from echolink.codec import pcm_resample_to_8k
    return pcm_resample_to_8k(pcm_24k, source_rate=24000)


# --- STT backends ---

async def _stt_openai(pcm_bytes: bytes) -> str:
    from openai import AsyncOpenAI
    import subprocess
    # Whisper API requires a file format (not raw PCM); wrap in WAV
    wav_bytes = _pcm_to_wav(pcm_bytes, sample_rate=8000)
    client = AsyncOpenAI()
    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=("audio.wav", wav_bytes, "audio/wav"),
    )
    return transcript.text


async def _stt_whisper_local(pcm_bytes: bytes) -> str:
    """
    Local whisper.cpp via subprocess.
    Requires: whisper.cpp compiled and `whisper` on PATH.
    # ponytail: subprocess approach keeps the dependency optional
    """
    import asyncio
    import subprocess
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(_pcm_to_wav(pcm_bytes, sample_rate=8000))
        wav_path = f.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "whisper", wav_path, "--output-format", "txt",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()
    finally:
        os.unlink(wav_path)


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 8000) -> bytes:
    """Wrap raw 16-bit mono PCM in a minimal WAV container."""
    import struct
    num_samples = len(pcm_bytes) // 2
    wav = io.BytesIO()
    wav.write(b"RIFF")
    wav.write(struct.pack("<I", 36 + len(pcm_bytes)))  # chunk size
    wav.write(b"WAVE")
    wav.write(b"fmt ")
    wav.write(struct.pack("<IHHIIHH",
        16,           # subchunk1 size
        1,            # PCM
        1,            # mono
        sample_rate,
        sample_rate * 2,  # byte rate
        2,            # block align
        16,           # bits per sample
    ))
    wav.write(b"data")
    wav.write(struct.pack("<I", len(pcm_bytes)))
    wav.write(pcm_bytes)
    return wav.getvalue()
