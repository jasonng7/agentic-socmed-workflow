import shutil
import subprocess
from pathlib import Path


def get_whisper_backend() -> str:
    """Detect available Whisper backend. Returns 'mlx' | 'openai' | 'none'."""
    try:
        import mlx_whisper  # noqa: F401
        return "mlx"
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401
        return "openai"
    except ImportError:
        pass
    return "none"


def get_whisper_info() -> str:
    """Human-readable string about which Whisper backend is available."""
    backend = get_whisper_backend()
    if backend == "mlx":
        return "Using mlx-whisper (whisper-large-v3-turbo) - Apple Silicon optimized"
    elif backend == "openai":
        return "Using openai-whisper (base model) - cross-platform"
    return "No Whisper backend installed. Install mlx-whisper (macOS) or openai-whisper (Linux)"


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


def transcribe_with_mlx(mp3_path: Path, model: str = "mlx-community/whisper-large-v3-turbo") -> str:
    """Transcribe using mlx_whisper. Tries multiple API signature variants."""
    from mlx_whisper import transcribe

    attempts = [
        {"path_or_hf_repo": model},
        {"model": model},
        {"model_path": model},
        {},
    ]
    last_error = None

    for kwargs in attempts:
        try:
            result = transcribe(str(mp3_path), **kwargs)
            if isinstance(result, dict):
                text = str(result.get("text", "")).strip()
            else:
                text = str(result).strip()
            if text:
                return text
        except TypeError as exc:
            last_error = exc

    raise RuntimeError(
        "mlx-whisper transcribe API signature did not match expected variants. "
        "Try upgrading mlx-whisper."
    ) from last_error


def transcribe_with_openai_whisper(mp3_path: Path, model: str = "base") -> str:
    """Transcribe using openai-whisper (for Linux VPS)."""
    import whisper

    wmodel = whisper.load_model(model)
    result = wmodel.transcribe(str(mp3_path))
    return result.get("text", "").strip()


def transcribe_audio(audio_path: Path, model: str | None = None) -> tuple[str, str]:
    """Unified transcription entry point. Auto-detects backend.
    Returns (transcript_text, backend_used).
    Raises RuntimeError if no backend available."""
    backend = get_whisper_backend()

    if backend == "mlx":
        mlx_model = model or "mlx-community/whisper-large-v3-turbo"
        return transcribe_with_mlx(audio_path, mlx_model), "mlx"
    elif backend == "openai":
        openai_model = model or "base"
        return transcribe_with_openai_whisper(audio_path, openai_model), "openai"
    else:
        raise RuntimeError(
            "No Whisper backend installed. Install mlx-whisper (macOS) or openai-whisper (Linux)"
        )


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
