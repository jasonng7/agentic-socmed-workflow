import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scraper_instagram import extract_caption as extract_instagram_caption
from scraper_instagram import extract_shortcode, process_instagram_urls
from scraper_xhs import process_xhs_urls
from scraper_youtube import process_youtube_urls
from url_router import extract_urls, group_routed_urls, route_urls
from utils import analyze_extraction_with_llm, load_env_config


DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


class ExtractRequest(BaseModel):
    input: str = Field(..., description="Free-form text containing one or more supported URLs.")
    user_preference: str = ""
    summarize: bool = True
    resolve_redirects: bool = True
    include_instagram_caption: bool = True
    include_instagram_transcript: bool = False
    include_youtube_metadata: bool = True
    include_youtube_transcript: bool = True
    include_xhs_caption: bool = True
    max_videos_per_collection: int = Field(default=5, ge=1, le=50)
    use_whisper: bool = False


class SummarizeRequest(BaseModel):
    extraction: Any
    user_preference: str = ""


def allowed_origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="Agentic Socmed Workflow Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def cleanup_file_paths(results: list[dict]) -> list[dict]:
    cleaned = []
    for result in results:
        item = dict(result)
        for key in ["video_path", "file_path", "transcript_path", "excel_path"]:
            if item.get(key):
                item[f"{key}_removed"] = True
                item[key] = None
        cleaned.append(item)
    return cleaned


def summarize_payload(extraction: Any, user_preference: str) -> str | None:
    env = load_env_config()
    if not env.get("api_key"):
        return None
    extraction_text = json.dumps(extraction, ensure_ascii=False, indent=2, default=str)
    return analyze_extraction_with_llm(
        extraction_text,
        user_preference,
        env["api_key"],
        env["base_url"],
        env["model"],
    )


def process_instagram_api(urls: list[str], request: ExtractRequest, temp_dir: Path) -> list[dict]:
    options = set()
    if request.include_instagram_caption:
        options.add("caption")
    if request.include_instagram_transcript:
        options.add("transcript")

    if not options:
        return []

    if request.include_instagram_transcript:
        results = process_instagram_urls(
            urls,
            options,
            "grouped",
            temp_dir / "instagram",
            whisper_enabled=request.use_whisper,
            llm_config=None,
            progress_callback=None,
        )
        return cleanup_file_paths(results)

    results = []
    for url in urls:
        item = {
            "platform": "instagram",
            "url": url,
            "shortcode": "",
            "caption": "",
            "transcript": "",
            "status": "ok",
            "error": None,
        }
        try:
            shortcode = extract_shortcode(url)
            item["shortcode"] = shortcode
            item["caption"] = extract_instagram_caption(shortcode)
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)
        results.append(item)
    return results


def process_youtube_api(urls: list[str], request: ExtractRequest, temp_dir: Path) -> list[dict]:
    if not request.include_youtube_metadata and not request.include_youtube_transcript:
        return []

    results = process_youtube_urls(
        urls,
        temp_dir / "youtube",
        extract_metadata=request.include_youtube_metadata,
        extract_transcript=request.include_youtube_transcript,
        download_videos=False,
        max_videos_per_collection=request.max_videos_per_collection,
        filter_type="All",
        browser="None",
        cookies_file=None,
        use_whisper=request.use_whisper,
        quality="Best",
        progress_callback=None,
    )
    return cleanup_file_paths(results)


def process_xhs_api(urls: list[str], request: ExtractRequest, temp_dir: Path) -> list[dict]:
    if not request.include_xhs_caption:
        return []
    results = process_xhs_urls(urls, temp_dir / "xhs", save_files=False, progress_callback=None)
    for item in results:
        item["platform"] = "xhs"
    return cleanup_file_paths(results)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/route")
def route(request: ExtractRequest) -> dict:
    urls = extract_urls(request.input)
    routed = route_urls(urls, resolve_redirects=request.resolve_redirects)
    return {"routes": [item.__dict__ for item in routed]}


@app.post("/summarize")
def summarize(request: SummarizeRequest) -> dict:
    summary = summarize_payload(request.extraction, request.user_preference)
    if summary is None:
        raise HTTPException(status_code=500, detail="LLM API key is not configured.")
    return {"summary": summary}


@app.post("/extract")
def extract(request: ExtractRequest) -> dict:
    urls = extract_urls(request.input)
    routed = route_urls(urls, resolve_redirects=request.resolve_redirects)
    grouped = group_routed_urls(routed)

    with tempfile.TemporaryDirectory(prefix="agentic-socmed-") as temp:
        temp_dir = Path(temp)
        results = {
            "instagram": process_instagram_api(grouped["instagram"], request, temp_dir),
            "youtube": process_youtube_api(grouped["youtube"], request, temp_dir),
            "xhs": process_xhs_api(grouped["xhs"], request, temp_dir),
        }
        shutil.rmtree(temp_dir, ignore_errors=True)

    payload = {
        "routes": [item.__dict__ for item in routed],
        "results": json_safe(results),
    }
    summary = summarize_payload(payload, request.user_preference) if request.summarize else None
    return {**payload, "summary": summary}
