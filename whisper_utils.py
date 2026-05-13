import os
import shutil
import subprocess
from pathlib import Path

import requests


def env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return os.environ.get(name, default).strip()


def get_whisper_backend() -> str:
    """Detect available transcription backend. Returns 'openai-api' | 'none'."""
    if env_value("OPENAI_API_KEY"):
        return "openai-api"
    return "none"


def get_whisper_info() -> str:
    """Human-readable string about which Whisper backend is available."""
    backend = get_whisper_backend()
    if backend == "openai-api":
        model = env_value("OPENAI_WHISPER_MODEL", "whisper-1") or "whisper-1"
        return f"Using OpenAI Audio Transcriptions API ({model})"
    return "OpenAI transcription is disabled because OPENAI_API_KEY is not configured."


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def extract_audio_with_ffmpeg(video_path: Path, mp3_path: Path) -> None:
    """Extract audio from video file using ffmpeg."""
    if not check_ffmpeg():
        raise RuntimeError(
            "ffmpeg is not installed. Install with: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
        )
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "2",
        str(mp3_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")


def transcribe_with_openai_api(audio_path: Path, model: str = "whisper-1") -> str:
    """Transcribe an audio file with OpenAI's hosted Audio Transcriptions API."""
    api_key = env_value("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI transcription.")

    base_url = env_value("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    timeout = int(env_value("OPENAI_TRANSCRIPTION_TIMEOUT_SECONDS", "600"))

    with audio_path.open("rb") as audio_file:
        response = requests.post(
            f"{base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "model": model,
                "response_format": "json",
            },
            files={"file": (audio_path.name, audio_file)},
            timeout=timeout,
        )

    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI transcription API HTTP {response.status_code}: {response.text}")

    data = response.json()
    return str(data.get("text", "")).strip()


def transcribe_audio(audio_path: Path, model: str | None = None) -> tuple[str, str]:
    """Unified transcription entry point.
    Returns (transcript_text, backend_used).
    Raises RuntimeError if no backend available."""
    audio_path = Path(audio_path)
    backend = get_whisper_backend()

    if backend == "openai-api":
        openai_model = model or env_value("OPENAI_WHISPER_MODEL", "whisper-1") or "whisper-1"
        return transcribe_with_openai_api(audio_path, openai_model), "openai-api"
    raise RuntimeError("OpenAI transcription is disabled because OPENAI_API_KEY is not configured.")


def video_to_transcript(video_path: Path, temp_dir: Path | None = None,
                        model: str | None = None) -> tuple[str, Path, Path]:
    """Full pipeline: video -> audio extraction -> transcription.
    Returns (transcript_text, video_path, audio_path).
    Caller responsible for audio cleanup."""
    if temp_dir is None:
        temp_dir = video_path.parent
    temp_dir.mkdir(parents=True, exist_ok=True)

    mp3_path = temp_dir / f"{video_path.stem}.mp3"
    extract_audio_with_ffmpeg(video_path, mp3_path)
    transcript, _backend = transcribe_audio(mp3_path, model)
    return transcript, video_path, mp3_path
