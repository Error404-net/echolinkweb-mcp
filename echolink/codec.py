"""
Audio format conversion utilities for EchoLink (8kHz 16-bit mono PCM).

The webapp backend handles GSM-FR codec; we only need PCM ↔ other formats.
ffmpeg handles MP3 decoding (from TTS APIs) and sample-rate conversion.
"""

import subprocess


def mp3_to_pcm_8k(mp3_bytes: bytes) -> bytes:
    """Convert MP3 (e.g. from OpenAI TTS) to 8kHz mono 16-bit PCM via ffmpeg."""
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", "-f", "s16le", "-ar", "8000", "-ac", "1", "pipe:1"],
        input=mp3_bytes,
        capture_output=True,
        check=True,
    )
    return result.stdout


def pcm_resample_to_8k(pcm_bytes: bytes, source_rate: int) -> bytes:
    """Resample PCM from any rate/channel to 8kHz mono 16-bit via ffmpeg."""
    if source_rate == 8000:
        return pcm_bytes
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "s16le", "-ar", str(source_rate), "-ac", "1", "-i", "pipe:0",
            "-f", "s16le", "-ar", "8000", "-ac", "1", "pipe:1",
        ],
        input=pcm_bytes,
        capture_output=True,
        check=True,
    )
    return result.stdout
