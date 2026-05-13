import os
import re
import shutil
import time
import traceback
from pathlib import Path

import instaloader
import streamlit as st

from utils import (
    get_output_dir,
    load_env_config,
    slugify_folder_name,
    summarize_transcript_with_llm,
    unique_dir_path,
)
from whisper_utils import extract_audio_with_ffmpeg, get_whisper_info, transcribe_audio


def extract_shortcode(url: str) -> str:
    """Extract shortcode from Instagram URL."""
    match = re.search(r"instagram\.com/(?:[^/]+/)?(?:reels?|p|tv)/([^/?#]+)", url)
    if not match:
        raise ValueError(f"Invalid Instagram reel/post URL: {url}")
    return match.group(1)


def find_downloaded_mp4(download_dir: Path, shortcode: str) -> Path:
    """Find the downloaded .mp4 file in a directory."""
    preferred = download_dir / f"{shortcode}.mp4"
    if preferred.exists():
        return preferred
    mp4_files = sorted(download_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4_files:
        raise FileNotFoundError(f"No .mp4 found in {download_dir}")
    return mp4_files[0]


def build_instaloader(**kwargs) -> instaloader.Instaloader:
    """Create an Instaloader instance and load a session when configured."""
    loader = instaloader.Instaloader(
        download_comments=False,
        save_metadata=False,
        download_geotags=False,
        download_pictures=False,
        download_video_thumbnails=False,
        **kwargs,
    )
    username = os.environ.get("INSTAGRAM_USERNAME", "").strip()
    session_file = os.environ.get("INSTAGRAM_SESSION_FILE", "").strip()
    if username and session_file and Path(session_file).exists():
        loader.load_session_from_file(username, session_file)
    return loader


def download_video(shortcode: str, output_dir: Path) -> Path:
    """Download Instagram reel/post video using instaloader."""
    temp_dir = output_dir / f"temp_{shortcode}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    loader = build_instaloader(
        dirname_pattern=str(temp_dir),
        filename_pattern="{shortcode}",
        post_metadata_txt_pattern="",
    )

    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    loader.download_post(post, target=str(temp_dir))

    downloaded_mp4 = find_downloaded_mp4(temp_dir, shortcode)
    final_path = output_dir / f"{shortcode}.mp4"
    if downloaded_mp4 != final_path:
        shutil.move(str(downloaded_mp4), str(final_path))

    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    return final_path


def extract_caption(shortcode: str) -> str:
    """Extract post caption text using configured session when available."""
    loader = build_instaloader()
    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    return (post.caption or "").strip()


def process_instagram_urls(
    urls: list[str],
    extract_options: set[str],
    output_structure: str,
    output_dir: Path,
    whisper_enabled: bool = True,
    llm_config: dict | None = None,
    progress_callback=None,
) -> list[dict]:
    """Process a list of Instagram URLs. Returns result dicts."""
    want_video = "video" in extract_options
    want_transcript = "transcript" in extract_options
    want_caption = "caption" in extract_options
    need_download = want_video or want_transcript

    results = []
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
        if progress_callback:
            progress_callback(i, len(urls), f"Processing: {url[:60]}...")

        result = {
            "shortcode": "", "url": url, "status": "ok",
            "video_path": None, "transcript": "", "caption": "",
            "error": None,
        }

        try:
            shortcode = extract_shortcode(url)
            result["shortcode"] = shortcode

            if output_structure == "separate":
                reel_dir = output_dir / shortcode
                reel_dir.mkdir(parents=True, exist_ok=True)
                video_path = reel_dir / f"{shortcode}.mp4"
                mp3_path = reel_dir / f"{shortcode}.mp3"
                txt_path = reel_dir / f"{shortcode}.txt"
                caption_path = reel_dir / f"{shortcode}_caption.txt"
            else:
                reel_dir = None
                video_path = output_dir / "videos" / f"{shortcode}.mp4"
                mp3_path = output_dir / "audio" / f"{shortcode}.mp3"
                txt_path = output_dir / "transcripts" / f"{shortcode}.txt"
                caption_path = output_dir / "captions" / f"{shortcode}_caption.txt"
                for p in [video_path, mp3_path, txt_path, caption_path]:
                    p.parent.mkdir(parents=True, exist_ok=True)

            if need_download:
                downloaded = download_video(shortcode, output_dir)
                if downloaded != video_path:
                    shutil.move(str(downloaded), str(video_path))
                result["video_path"] = str(video_path)

            if want_caption:
                try:
                    caption_text = extract_caption(shortcode)
                    result["caption"] = caption_text
                    caption_path.write_text(caption_text, encoding="utf-8")
                except Exception as exc:
                    result["caption"] = ""
                    result["caption_error"] = str(exc)

            if want_transcript:
                transcript = ""
                try:
                    extract_audio_with_ffmpeg(video_path, mp3_path)
                    transcript, backend = transcribe_audio(mp3_path)
                    txt_path.write_text(transcript, encoding="utf-8")
                except Exception as exc:
                    transcript = f"[Transcription error: {exc}]"
                result["transcript"] = transcript

                if not want_video and video_path.exists():
                    video_path.unlink()
                if mp3_path.exists():
                    mp3_path.unlink()
            elif not want_video and video_path.exists():
                video_path.unlink()

            if want_transcript and result["transcript"] and not result["transcript"].startswith("["):
                if not want_video and video_path.exists():
                    video_path.unlink()

            if output_structure == "separate" and want_transcript and result["transcript"] and llm_config and llm_config.get("api_key"):
                try:
                    title = summarize_transcript_with_llm(
                        result["transcript"],
                        llm_config["api_key"],
                        llm_config["base_url"],
                        llm_config["model"],
                    )
                    new_slug = slugify_folder_name(title, fallback=shortcode)
                    target_dir = unique_dir_path(output_dir, new_slug)
                    if target_dir != reel_dir and reel_dir and reel_dir.exists():
                        reel_dir.rename(target_dir)
                except Exception:
                    pass

        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            traceback.print_exc()

        results.append(result)

        if i < len(urls) - 1:
            time.sleep(2)

    return results


def render_instagram_sidebar() -> dict:
    """Render Instagram-specific sidebar controls."""
    with st.sidebar:
        st.markdown("### Instagram Settings")

        extract_options = st.multiselect(
            "What to extract",
            ["Video", "Transcript", "Caption"],
            default=["Video", "Transcript"],
        )
        extract_set = {opt.lower() for opt in extract_options}

        output_structure = st.radio(
            "Output structure",
            ["Separate (one folder per video)", "Grouped (by file type)"],
        )
        structure = "separate" if "Separate" in output_structure else "grouped"

        st.divider()
        st.markdown("### LLM Folder Naming")
        llm_enabled = st.checkbox("Enable LLM folder naming", value=False,
                                   help="Uses OpenRouter API to generate descriptive folder names from transcripts")
        llm_config = None
        if llm_enabled:
            env = load_env_config()
            llm_config = {
                "api_key": st.text_input("API Key", value=env["api_key"], type="password"),
                "base_url": st.text_input("Base URL", value=env["base_url"]),
                "model": st.text_input("Model", value=env["model"]),
            }

        st.info(get_whisper_info())

    return {
        "extract_options": extract_set,
        "output_structure": structure,
        "llm_config": llm_config,
    }


def render_instagram_ui(config: dict) -> None:
    """Render the Instagram interface in the main area."""
    st.markdown("### Instagram Video Downloader & Transcriber")

    urls_input = st.text_area(
        "Paste Instagram reel/post URLs (one per line)",
        placeholder="https://www.instagram.com/reel/...\nhttps://www.instagram.com/p/...",
        height=150,
    )

    extract_options = config.get("extract_options", {"video", "transcript"})
    if not extract_options:
        st.warning("Select at least one extraction option in the sidebar.")
        return

    if st.button("Process URLs", use_container_width=True):
        urls = [u.strip() for u in urls_input.split("\n") if u.strip()]
        if not urls:
            st.warning("Please enter at least one Instagram URL.")
            return

        output_dir = get_output_dir("instagram", config.get("output_base", "./downloads"))
        output_structure = config.get("output_structure", "separate")
        whisper_enabled = config.get("whisper_enabled", True)
        llm_config = config.get("llm_config")

        progress_bar = st.progress(0, text="Starting...")
        log_placeholder = st.empty()
        log_lines = []

        def on_progress(current, total, message):
            progress_bar.progress(current / total, text=f"[{current}/{total}] {message}")
            log_lines.append(message)
            log_placeholder.markdown(
                '<div class="log-box">' + "<br>".join(log_lines[-10:]) + "</div>",
                unsafe_allow_html=True,
            )

        results = process_instagram_urls(
            urls, extract_options, output_structure, output_dir,
            whisper_enabled, llm_config, on_progress,
        )
        progress_bar.progress(1.0, text="Done!")

        st.divider()
        ok_count = sum(1 for r in results if r["status"] == "ok")
        st.success(f"Processed {ok_count}/{len(results)} URLs")

        for r in results:
            badge = "badge-ok" if r["status"] == "ok" else "badge-fail"
            status_label = "OK" if r["status"] == "ok" else r["status"]
            st.markdown(
                f'<span class="badge {badge}">{status_label}</span> '
                f'<strong>{r["shortcode"]}</strong> — {r["url"]}',
                unsafe_allow_html=True,
            )
            if r["video_path"]:
                st.caption(f"Video: {r['video_path']}")
            if r["transcript"] and not r["transcript"].startswith("["):
                with st.expander(f"Transcript ({len(r['transcript'])} chars)"):
                    st.text(r["transcript"][:1000])
            if r["caption"]:
                with st.expander(f"Caption ({len(r['caption'])} chars)"):
                    st.text(r["caption"][:500])
            if r["error"]:
                st.error(r["error"])
