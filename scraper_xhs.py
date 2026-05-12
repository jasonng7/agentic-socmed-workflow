import re
from pathlib import Path

import requests
import streamlit as st
from bs4 import BeautifulSoup

from utils import get_output_dir

XHS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def extract_post_id(url: str, fallback_index: int = 0) -> str:
    """Extract post ID from XHS URL."""
    match = re.search(r"/([a-zA-Z0-9]+)(?:\?|$)", url)
    if match:
        return match.group(1)
    return f"post_{fallback_index + 1}"


def scrape_xhs_caption(url: str) -> str | None:
    """Scrape caption from a single XHS post URL."""
    response = requests.get(url, headers=XHS_HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc and meta_desc.get("content"):
        return meta_desc["content"].strip()
    return None


def process_xhs_urls(urls: list[str], output_dir: Path,
                     save_files: bool = True,
                     progress_callback=None) -> list[dict]:
    """Process list of XHS URLs. Returns result dicts."""
    results = []
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
        if progress_callback:
            progress_callback(i, len(urls), f"Processing: {url[:60]}...")
        post_id = extract_post_id(url, i)
        result = {"url": url, "post_id": post_id, "caption": None,
                  "status": "ok", "file_path": None, "error": None}
        try:
            caption = scrape_xhs_caption(url)
            if caption:
                result["caption"] = caption
                if save_files:
                    filepath = output_dir / f"caption_{post_id}.txt"
                    filepath.write_text(caption, encoding="utf-8")
                    result["file_path"] = str(filepath)
            else:
                result["status"] = "no_caption"
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
        results.append(result)
    return results


def render_xhs_sidebar() -> dict:
    """Render XHS-specific sidebar controls."""
    with st.sidebar:
        st.markdown("### XHS Settings")
        save_files = st.checkbox("Save .txt files to disk", value=True)
        st.info("XHS caption extraction is unauthenticated. Works for public posts.")
    return {"save_files": save_files}


def render_xhs_ui(config: dict) -> None:
    """Render the XHS interface in the main area."""
    st.markdown("### Xiaohongshu Caption Extractor")

    urls_input = st.text_area(
        "Paste XHS URLs (comma-separated)",
        placeholder="https://www.xiaohongshu.com/explore/...",
        height=100,
    )

    if st.button("Extract Captions", use_container_width=True):
        urls = [u.strip() for u in urls_input.split(",") if u.strip()]
        if not urls:
            st.warning("Please enter at least one XHS URL.")
            return

        output_dir = get_output_dir("xhs", config.get("output_base", "./downloads"))
        save_files = config.get("save_files", True)

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

        results = process_xhs_urls(urls, output_dir, save_files, on_progress)
        progress_bar.progress(1.0, text="Done!")

        st.divider()
        ok_count = sum(1 for r in results if r["status"] == "ok")
        st.success(f"Extracted {ok_count}/{len(results)} captions")

        for r in results:
            status_color = "#6ee7b7" if r["status"] == "ok" else "#f87171"
            status_label = "OK" if r["status"] == "ok" else r["status"]
            st.markdown(
                f'<span class="badge {"badge-ok" if r["status"] == "ok" else "badge-fail"}">'
                f'{status_label}</span> {r["url"]}',
                unsafe_allow_html=True,
            )
            if r["caption"]:
                with st.expander(f"Caption ({len(r['caption'])} chars)"):
                    st.text(r["caption"])
                if r["file_path"]:
                    st.caption(f"Saved to: {r['file_path']}")
            elif r["error"]:
                st.error(r["error"])
