import json
import os
import random
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import instaloader
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from scraper_instagram import extract_caption as extract_instagram_caption
from scraper_instagram import download_video as download_instagram_video
from scraper_instagram import extract_shortcode, process_instagram_urls
from scraper_xhs import process_xhs_urls
from scraper_youtube import download_video_ytdlp, get_single_video_metadata, get_transcript, is_youtube_collection_url, process_youtube_urls
from url_router import extract_urls, group_routed_urls, route_urls
from url_router import detect_platform
from utils import analyze_extraction_with_llm, load_env_config


DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


class ExtractRequest(BaseModel):
    input: str = Field(..., description="Free-form text containing one or more supported URLs.")
    user_preference: str = ""
    summarize: bool = False
    resolve_redirects: bool = True
    include_instagram_caption: bool = True
    include_instagram_transcript: bool = True
    include_youtube_metadata: bool = True
    include_youtube_transcript: bool = True
    include_xhs_caption: bool = True
    max_videos_per_collection: int = Field(default=5, ge=1, le=50)
    use_whisper: bool = True


class SummarizeRequest(BaseModel):
    extraction: Any
    user_preference: str = ""


def allowed_origins() -> list[str]:
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        return DEFAULT_ALLOWED_ORIGINS
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


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


def newest_file(directory: Path) -> Path | None:
    files = [path for path in directory.rglob("*") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


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


def polite_delay(stage: str, multiplier: float = 1.0) -> float:
    min_delay = env_float("SCRAPER_MIN_DELAY_SECONDS", 2.0)
    max_delay = env_float("SCRAPER_MAX_DELAY_SECONDS", 6.0)
    if max_delay < min_delay:
        max_delay = min_delay
    delay = random.uniform(min_delay, max_delay) * multiplier
    time.sleep(delay)
    return round(delay, 2)


def configured_youtube_cookies_file() -> str | None:
    path = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if path and Path(path).exists():
        return path
    return None


def configured_youtube_browser() -> str:
    browser = os.environ.get("YOUTUBE_BROWSER", "").strip()
    return browser or "None"


def extract_instagram_caption_configured(shortcode: str) -> tuple[str, str]:
    username = os.environ.get("INSTAGRAM_USERNAME", "").strip()
    session_file = os.environ.get("INSTAGRAM_SESSION_FILE", "").strip()

    if username and session_file and Path(session_file).exists():
        loader = instaloader.Instaloader(
            download_comments=False,
            save_metadata=False,
            download_geotags=False,
            download_pictures=False,
            download_video_thumbnails=False,
        )
        loader.load_session_from_file(username, session_file)
        post = instaloader.Post.from_shortcode(loader.context, shortcode)
        return (post.caption or "").strip(), "instaloader-session"

    return extract_instagram_caption(shortcode), "instaloader-anonymous"


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
        delay = polite_delay("instagram")
        item = {
            "platform": "instagram",
            "url": url,
            "shortcode": "",
            "caption": "",
            "transcript": "",
            "delay_seconds": delay,
            "status": "ok",
            "error": None,
        }
        try:
            shortcode = extract_shortcode(url)
            item["shortcode"] = shortcode
            item["caption"], item["caption_method"] = extract_instagram_caption_configured(shortcode)
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)
        results.append(item)
    return results


def extract_youtube_video_id(url: str) -> tuple[str | None, bool]:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parsed.path.strip("/")

    if host == "youtu.be" and path:
        return path.split("/")[0], False

    if path.startswith("shorts/"):
        return path.split("/")[1] if len(path.split("/")) > 1 else None, True

    if path.startswith("watch"):
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        return video_id, False

    match = re.search(r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{6,})", url)
    if match:
        return match.group(1), "/shorts/" in url

    return None, False


def process_single_youtube_api(url: str, request: ExtractRequest) -> dict:
    delay = polite_delay("youtube")
    use_whisper = request.use_whisper or env_bool("BACKEND_USE_WHISPER", False)
    video_id, is_short = extract_youtube_video_id(url)
    cookies_file = configured_youtube_cookies_file()
    browser = "None" if cookies_file else configured_youtube_browser()
    item = {
        "platform": "youtube",
        "source_input_url": url,
        "url": url,
        "id": video_id or "",
        "title": "",
        "duration": "",
        "upload_date": "",
        "views": "",
        "likes": "",
        "is_short": is_short,
        "caption": "",
        "transcript": "",
        "transcript_status": "not_requested" if not request.include_youtube_transcript else "pending",
        "transcript_method": "",
        "metadata_status": "not_requested" if not request.include_youtube_metadata else "pending",
        "cookies_used": bool(cookies_file),
        "browser_cookies": browser if browser != "None" else "",
        "whisper_enabled": use_whisper,
        "delay_seconds": delay,
        "status": "ok",
        "error": None,
    }

    if request.include_youtube_metadata:
        try:
            metadata = get_single_video_metadata(url, browser=browser, cookies_file=cookies_file)
            item.update(metadata)
            item["platform"] = "youtube"
            item["metadata_status"] = "ok"
            video_id = metadata.get("id") or video_id
            is_short = bool(metadata.get("is_short", is_short))
        except Exception as exc:
            item["metadata_status"] = "error"
            item["metadata_error"] = str(exc)

    if request.include_youtube_transcript:
        polite_delay("youtube-transcript", multiplier=0.75)
        if not video_id:
            item["transcript_status"] = "error"
            item["transcript_method"] = "video-id"
            item["error"] = "Could not extract YouTube video id."
        else:
            transcript, status, method = get_transcript(
                video_id,
                is_short=is_short,
                use_whisper=use_whisper,
                browser=browser,
                cookies_file=cookies_file,
            )
            item["transcript"] = transcript
            item["transcript_status"] = status
            item["transcript_method"] = method

    if item.get("metadata_status") == "error" and item.get("transcript_status") not in {"ok", "not_requested"}:
        item["status"] = "partial"
    elif item.get("metadata_status") == "error":
        item["status"] = "partial"

    return item


def process_youtube_api(urls: list[str], request: ExtractRequest, temp_dir: Path) -> list[dict]:
    if not request.include_youtube_metadata and not request.include_youtube_transcript:
        return []

    results = []
    collections = []
    for url in urls:
        if is_youtube_collection_url(url):
            collections.append(url)
        else:
            results.append(process_single_youtube_api(url, request))

    if collections:
        polite_delay("youtube-collection")
        cookies_file = configured_youtube_cookies_file()
        browser = "None" if cookies_file else configured_youtube_browser()
        use_whisper = request.use_whisper or env_bool("BACKEND_USE_WHISPER", False)
        collection_results = process_youtube_urls(
            collections,
            temp_dir / "youtube",
            extract_metadata=request.include_youtube_metadata,
            extract_transcript=request.include_youtube_transcript,
            download_videos=False,
            max_videos_per_collection=request.max_videos_per_collection,
            filter_type="All",
            browser=browser,
            cookies_file=cookies_file,
            use_whisper=use_whisper,
            quality="Best",
            progress_callback=None,
        )
        results.extend(cleanup_file_paths(collection_results))

    return cleanup_file_paths(results)


def process_xhs_api(urls: list[str], request: ExtractRequest, temp_dir: Path) -> list[dict]:
    if not request.include_xhs_caption:
        return []
    if urls:
        polite_delay("xhs", multiplier=0.5)
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


@app.get("/download-video")
def download_video(url: str = Query(..., min_length=8)) -> FileResponse:
    platform, _reason = detect_platform(url)
    if platform not in {"instagram", "youtube"}:
        raise HTTPException(status_code=400, detail="Video download is supported for Instagram and YouTube URLs.")

    temp_dir = Path(tempfile.mkdtemp(prefix="agentic-video-download-"))
    cookies_file = configured_youtube_cookies_file()
    browser = "None" if cookies_file else configured_youtube_browser()

    try:
        if platform == "instagram":
            shortcode = extract_shortcode(url)
            file_path = download_instagram_video(shortcode, temp_dir)
        else:
            result = download_video_ytdlp(
                url,
                output_dir=str(temp_dir),
                browser=browser,
                cookies_file=cookies_file,
                quality="Best",
            )
            if result.returncode != 0:
                raise HTTPException(status_code=502, detail=result.stderr or "YouTube video download failed.")
            file_path = newest_file(temp_dir)

        if not file_path or not file_path.exists():
            raise HTTPException(status_code=502, detail="Video download did not produce a file.")

        return FileResponse(
            path=file_path,
            filename=file_path.name,
            media_type="application/octet-stream",
            background=BackgroundTask(shutil.rmtree, temp_dir, ignore_errors=True),
        )
    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
