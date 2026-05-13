import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


def _load_streamlit_secret(key: str) -> str:
    """Read a Streamlit secret if Streamlit is available and configured."""
    try:
        import streamlit as st

        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""


def load_env_config() -> dict:
    """Load LLM env vars from OpenAI first, then OpenRouter compatibility vars."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip() or _load_streamlit_secret("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or _load_streamlit_secret("OPENAI_BASE_URL")
    model = os.environ.get("OPENAI_MODEL", "").strip() or _load_streamlit_secret("OPENAI_MODEL")
    provider = "openai" if api_key else "openrouter"

    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip() or _load_streamlit_secret("OPENROUTER_API_KEY")
        base_url = os.environ.get("OPENROUTER_BASE_URL", "").strip() or _load_streamlit_secret("OPENROUTER_BASE_URL")
        model = os.environ.get("OPENROUTER_MODEL", "").strip() or _load_streamlit_secret("OPENROUTER_MODEL")

    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            if not api_key:
                api_key = os.getenv("OPENAI_API_KEY", "").strip()
                base_url = os.getenv("OPENAI_BASE_URL", "").strip()
                model = os.getenv("OPENAI_MODEL", "").strip()
                provider = "openai" if api_key else provider
            if not api_key:
                api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
                base_url = os.getenv("OPENROUTER_BASE_URL", "").strip()
                model = os.getenv("OPENROUTER_MODEL", "").strip()
                provider = "openrouter" if api_key else provider
        except ImportError:
            pass

    if not base_url:
        base_url = "https://api.openai.com/v1" if provider == "openai" else "https://openrouter.ai/api/v1"
    if not model:
        model = "gpt-4o-mini" if provider == "openai" else "google/gemini-2.0-flash-lite-preview-02-05:free"

    return {
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "provider": provider,
    }


def call_chat_completion(messages: list[dict], api_key: str, base_url: str,
                         model: str, temperature: float = 0.2) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/jason/agentic-socmed-workflow",
        "X-Title": "Agentic Socmed Workflow",
    }

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM API connection failed: {exc.reason}") from exc

    try:
        content = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LLM response format: {body}") from exc

    if not content:
        raise RuntimeError("LLM response was empty.")

    return content


def summarize_transcript_with_llm(transcript: str, api_key: str,
                                   base_url: str, model: str) -> str:
    """Generate short folder name from transcript via LLM API."""
    prompt = (
        "You create concise folder names. "
        "Return only a short title (3 to 8 words), no punctuation except spaces, no numbering."
    )
    title = call_chat_completion(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Generate a short folder title for this transcript:\n\n"
                    f"{transcript[:12000]}"
                ),
            },
        ],
        api_key,
        base_url,
        model,
    )

    return title


def analyze_extraction_with_llm(extraction_text: str, user_request: str,
                                api_key: str, base_url: str, model: str) -> str:
    """Analyze extracted captions and transcripts according to the user's request."""
    system_prompt = (
        "You analyze public social media extractions for a user. "
        "Follow the user's request exactly, using transcripts and captions as the source of truth. "
        "Use metadata only as supporting context. "
        "Do not invent facts that are not present. "
        "If the user asks for a specific format, structure, language, level of detail, or focus, "
        "honor that instead of applying a fixed summary template."
    )
    user_prompt = (
        f"User request:\n{user_request or 'Summarize the extracted content.'}\n\n"
        "Extracted data to use. Prioritize fields named caption and transcript.\n\n"
        f"{extraction_text[:40000]}"
    )
    return call_chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        api_key,
        base_url,
        model,
        temperature=0.1,
    )


def slugify_folder_name(text: str, fallback: str) -> str:
    """Convert text to filesystem-safe slug."""
    cleaned = re.sub(r"\s+", " ", text).strip().lower()
    cleaned = re.sub(r"[^a-z0-9\s-]", "", cleaned)
    cleaned = cleaned.replace(" ", "-")
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        return fallback
    return cleaned[:80].rstrip("-")


def unique_dir_path(parent: Path, desired_name: str) -> Path:
    """Unique directory path, appending -2, -3 etc. if exists."""
    candidate = parent / desired_name
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        numbered = parent / f"{desired_name}-{index}"
        if not numbered.exists():
            return numbered
        index += 1


def get_output_dir(platform: str, base_dir: str = "./downloads") -> Path:
    """Create and return downloads/{platform}/ directory."""
    path = Path(base_dir) / platform
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_number(val) -> str:
    """Format numbers with K/M suffixes."""
    try:
        n = int(val)
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
    except (ValueError, TypeError):
        return str(val) if val else "N/A"
