import json
import platform as platform_mod
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import streamlit as st

from scraper_instagram import process_instagram_urls
from scraper_xhs import process_xhs_urls
from scraper_youtube import process_youtube_urls
from url_router import extract_urls, group_routed_urls, route_urls
from utils import analyze_extraction_with_llm, get_output_dir, load_env_config
from whisper_utils import check_ffmpeg, get_whisper_info


st.set_page_config(
    page_title="Agentic Socmed Workflow",
    page_icon="",
    layout="wide",
)


st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #101114; color: #eceff3; }
section[data-testid="stSidebar"] {
    background: #17191f;
    border-right: 1px solid #2b3038;
}
.block-container { padding-top: 1.6rem; max-width: 1180px; }
h1, h2, h3 { color: #eceff3; font-weight: 600; letter-spacing: 0; }
.route-row {
    background: #17191f;
    border: 1px solid #2b3038;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
}
.route-title { font-weight: 600; font-size: 0.88rem; color: #eceff3; }
.route-meta { font-size: 0.76rem; color: #a2aab7; font-family: 'DM Mono', monospace; word-break: break-word; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.68rem;
    font-weight: 600;
    margin-right: 6px;
}
.badge-instagram { background: #3a2335; color: #f0a2d6; }
.badge-youtube { background: #3b2020; color: #ff9b9b; }
.badge-xhs { background: #332c1d; color: #ffd27a; }
.badge-ok { background: #1e352b; color: #70e1ad; }
.badge-fail { background: #3a1f22; color: #ff8b8b; }
.badge-unsupported { background: #242933; color: #b8c0cc; }
.log-box {
    background: #0d0f12;
    border: 1px solid #2b3038;
    border-radius: 8px;
    padding: 12px 14px;
    font-family: 'DM Mono', monospace;
    font-size: 0.76rem;
    color: #a2aab7;
    max-height: 260px;
    overflow-y: auto;
}
.stButton > button {
    background: #70e1ad !important;
    color: #0a0d0f !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 8px !important;
}
.stButton > button[kind="secondary"] {
    background: #17191f !important;
    color: #eceff3 !important;
    border: 1px solid #2b3038 !important;
}
.stTextInput > div > input,
.stNumberInput > div > input,
.stTextArea textarea {
    background: #17191f !important;
    border: 1px solid #2b3038 !important;
    color: #eceff3 !important;
    border-radius: 8px !important;
}
hr { border-color: #2b3038; }
</style>
""",
    unsafe_allow_html=True,
)


PLATFORM_LABELS = {
    "instagram": "Instagram",
    "youtube": "YouTube",
    "xhs": "RedNote / Xiaohongshu",
    "unsupported": "Unsupported",
}


def append_log(lines: list[str], placeholder, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    lines.append(f"[{timestamp}] {message}")
    placeholder.markdown('<div class="log-box">' + "<br>".join(lines[-16:]) + "</div>", unsafe_allow_html=True)


def platform_progress(platform: str, lines: list[str], placeholder):
    def _callback(current, total, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        lines.append(f"[{timestamp}] {PLATFORM_LABELS.get(platform, platform)} -> {message}")

    return _callback


def compact_result_text(results_by_platform: dict[str, list[dict]]) -> str:
    chunks = []
    for platform, results in results_by_platform.items():
        chunks.append(f"\n## {PLATFORM_LABELS.get(platform, platform)}")
        for index, item in enumerate(results, 1):
            status = item.get("status") or item.get("transcript_status") or "unknown"
            chunks.append(f"\n### Item {index} - {status}")
            for key in [
                "url",
                "source_input_url",
                "title",
                "shortcode",
                "post_id",
                "caption",
                "transcript",
                "transcript_status",
                "transcript_method",
                "video_path",
                "file_path",
                "transcript_path",
                "excel_path",
                "error",
            ]:
                value = item.get(key)
                if value:
                    text = str(value)
                    if key in {"caption", "transcript"} and len(text) > 5000:
                        text = text[:5000] + "\n[truncated]"
                    chunks.append(f"{key}: {text}")
    return "\n".join(chunks).strip()


def write_run_report(
    output_base: str,
    routed_rows,
    results_by_platform: dict[str, list[dict]],
    user_request: str,
    llm_summary: str | None,
) -> Path:
    output_dir = Path(output_base) / "agentic_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"run_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    route_lines = [
        f"- {row.original_url} -> {row.platform} -> {row.resolved_url}"
        + (f" (resolve warning: {row.error})" if row.error else "")
        for row in routed_rows
    ]
    extraction_text = compact_result_text(results_by_platform)
    body = [
        "Agentic Socmed Workflow Run Summary",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "User extraction preference:",
        user_request or "No additional preference provided.",
        "",
        "Routing:",
        "\n".join(route_lines) if route_lines else "No URLs detected.",
        "",
        "LLM Analysis:",
        llm_summary or "LLM analysis was disabled or unavailable.",
        "",
        "Raw Extraction Summary:",
        extraction_text or "No extraction results.",
        "",
        "Raw JSON:",
        json.dumps(results_by_platform, indent=2, ensure_ascii=False, default=str),
    ]
    report_path.write_text("\n".join(body), encoding="utf-8")
    return report_path


def write_llm_summary_file(output_base: str, routed_rows, user_request: str,
                           llm_summary: str) -> Path:
    output_dir = Path(output_base) / "agentic_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / f"llm_content_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    source_lines = [f"- {row.platform}: {row.resolved_url}" for row in routed_rows if row.platform != "unsupported"]
    body = [
        "LLM Content Summary",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Primary source rule:",
        "This summary is based primarily on extracted video transcripts and captions.",
        "",
        "User extraction preference:",
        user_request or "No additional preference provided.",
        "",
        "Sources:",
        "\n".join(source_lines) if source_lines else "No supported sources.",
        "",
        llm_summary,
    ]
    summary_path.write_text("\n".join(body), encoding="utf-8")
    return summary_path


with st.sidebar:
    st.markdown("### Runtime")
    output_base = st.text_input("Output directory", value="./outputs")
    resolve_redirects = st.checkbox("Resolve short-link redirects", value=True)
    max_workers = int(st.slider("Concurrent platform workers", min_value=1, max_value=3, value=2))

    st.divider()
    st.markdown("### LLM Analysis")
    llm_enabled = st.checkbox("Create content summary .txt", value=True)
    llm_env = load_env_config()
    llm_api_key = st.text_input("API key", value=llm_env["api_key"], type="password")
    llm_base_url = st.text_input("Base URL", value=llm_env["base_url"])
    llm_model = st.text_input("Model", value=llm_env["model"])

    st.divider()
    st.markdown("### System")
    st.caption(f"Platform: {platform_mod.system()}")
    st.caption(f"Python: {platform_mod.python_version()}")
    st.caption(get_whisper_info())


st.title("Agentic Socmed Workflow")

if not check_ffmpeg():
    st.warning(
        "ffmpeg is not installed. Video-to-audio extraction and Whisper fallback will not work."
    )

input_text = st.text_area(
    "Input",
    placeholder=(
        "Paste any mix of Instagram, YouTube, and RedNote/Xiaohongshu links here. "
        "You can paste one URL, many URLs, or text that contains URLs."
    ),
    height=150,
)

user_request = st.text_area(
    "What information do you want extracted or emphasized?",
    placeholder="Example: identify travel places, food locations, restaurant names, prices, key recommendations, hooks, CTA...",
    height=90,
)

urls = extract_urls(input_text)
routed_rows = route_urls(urls, resolve_redirects=resolve_redirects) if urls else []
grouped = group_routed_urls(routed_rows)

if urls:
    st.markdown("### Detected Routes")
    for row in routed_rows:
        badge_class = f"badge-{row.platform}" if row.platform in {"instagram", "youtube", "xhs"} else "badge-unsupported"
        st.markdown(
            f'<div class="route-row"><div class="route-title">'
            f'<span class="badge {badge_class}">{PLATFORM_LABELS.get(row.platform, row.platform)}</span>'
            f'{row.reason}</div><div class="route-meta">{row.original_url} -> {row.resolved_url}</div></div>',
            unsafe_allow_html=True,
        )

supported_count = sum(len(v) for v in grouped.values())
unsupported = [row for row in routed_rows if row.platform == "unsupported"]

if unsupported:
    st.error(f"{len(unsupported)} URL(s) are unsupported -> Instagram, YouTube, and RedNote/Xiaohongshu are supported for now.")

if supported_count:
    st.divider()
    st.markdown("### Extraction Settings")

    configs = {}
    if grouped["instagram"]:
        with st.expander(f"Instagram ({len(grouped['instagram'])})", expanded=True):
            ig_options = st.multiselect(
                "What to extract from Instagram",
                ["Video", "Transcript", "Caption"],
                default=["Transcript", "Caption"],
            )
            ig_structure_label = st.radio(
                "Instagram output structure",
                ["Separate (one folder per post)", "Grouped (by file type)"],
                horizontal=True,
            )
            configs["instagram"] = {
                "extract_options": {item.lower() for item in ig_options},
                "output_structure": "separate" if "Separate" in ig_structure_label else "grouped",
            }

    if grouped["youtube"]:
        with st.expander(f"YouTube ({len(grouped['youtube'])})", expanded=True):
            yt_cols = st.columns(3)
            with yt_cols[0]:
                yt_metadata = st.checkbox("Save metadata Excel", value=True)
                yt_transcript = st.checkbox("Extract transcripts", value=True)
                yt_download = st.checkbox("Download videos", value=False)
            with yt_cols[1]:
                yt_max_videos = int(st.number_input("Max videos per channel/playlist", min_value=1, max_value=500, value=20))
                yt_filter_type = st.selectbox("Filter by type", ["All", "Shorts only", "Videos only"])
            with yt_cols[2]:
                yt_browser = st.selectbox("Browser cookies", ["None", "Safari", "Chrome", "Firefox", "Edge"], index=0)
                yt_cookies = st.text_input("Manual cookies.txt path", value="")
                yt_quality = st.selectbox("Download quality", ["Best", "2160p (4K)", "1080p (HD)", "720p", "480p", "Audio Only (MP3)"])
                yt_whisper = st.checkbox("Whisper fallback", value=True)
            configs["youtube"] = {
                "extract_metadata": yt_metadata,
                "extract_transcript": yt_transcript,
                "download_videos": yt_download,
                "max_videos_per_collection": yt_max_videos,
                "filter_type": yt_filter_type,
                "browser": yt_browser,
                "cookies_file": yt_cookies.strip() or None,
                "quality": yt_quality,
                "use_whisper": yt_whisper,
            }

    if grouped["xhs"]:
        with st.expander(f"RedNote / Xiaohongshu ({len(grouped['xhs'])})", expanded=True):
            xhs_save_files = st.checkbox("Save caption .txt files", value=True)
            configs["xhs"] = {"save_files": xhs_save_files}

    run_btn = st.button("Run Agentic Workflow", type="primary", use_container_width=True)
else:
    run_btn = False


if run_btn:
    if not supported_count:
        st.error("No supported URLs detected.")
        st.stop()
    if grouped["instagram"] and not configs.get("instagram", {}).get("extract_options"):
        st.error("Select at least one Instagram extraction option.")
        st.stop()

    progress = st.progress(0, text="Starting workflow...")
    log_placeholder = st.empty()
    log_lines: list[str] = []
    results_by_platform: dict[str, list[dict]] = {}

    jobs = {}
    total_jobs = len([platform for platform, values in grouped.items() if values])
    completed_jobs = 0

    def run_platform(platform: str):
        platform_output_dir = get_output_dir(platform, output_base)
        if platform == "instagram":
            cfg = configs["instagram"]
            return process_instagram_urls(
                grouped["instagram"],
                cfg["extract_options"],
                cfg["output_structure"],
                platform_output_dir,
                whisper_enabled=True,
                llm_config={
                    "api_key": llm_api_key,
                    "base_url": llm_base_url,
                    "model": llm_model,
                } if llm_api_key else None,
                progress_callback=platform_progress(platform, log_lines, log_placeholder),
            )
        if platform == "youtube":
            cfg = configs["youtube"]
            return process_youtube_urls(
                grouped["youtube"],
                platform_output_dir,
                progress_callback=platform_progress(platform, log_lines, log_placeholder),
                **cfg,
            )
        if platform == "xhs":
            cfg = configs["xhs"]
            return process_xhs_urls(
                grouped["xhs"],
                platform_output_dir,
                save_files=cfg["save_files"],
                progress_callback=platform_progress(platform, log_lines, log_placeholder),
            )
        return []

    append_log(log_lines, log_placeholder, f"Detected {supported_count} supported URL(s) across {total_jobs} platform workflow(s).")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for platform, values in grouped.items():
            if values:
                append_log(log_lines, log_placeholder, f"Queued {PLATFORM_LABELS[platform]} workflow with {len(values)} URL(s).")
                jobs[executor.submit(run_platform, platform)] = platform

        for future in as_completed(jobs):
            platform = jobs[future]
            try:
                results_by_platform[platform] = future.result()
                append_log(log_lines, log_placeholder, f"{PLATFORM_LABELS[platform]} workflow finished.")
            except Exception as exc:
                results_by_platform[platform] = [{
                    "platform": platform,
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }]
                append_log(log_lines, log_placeholder, f"{PLATFORM_LABELS[platform]} workflow failed -> {exc}")
            completed_jobs += 1
            progress.progress(completed_jobs / total_jobs, text=f"Completed {completed_jobs}/{total_jobs} platform workflow(s)")

    extraction_text = compact_result_text(results_by_platform)
    llm_summary = None
    llm_summary_ok = False
    if llm_enabled and llm_api_key and extraction_text:
        with st.spinner("Analyzing extracted information with LLM..."):
            try:
                llm_summary = analyze_extraction_with_llm(
                    extraction_text,
                    user_request,
                    llm_api_key,
                    llm_base_url,
                    llm_model,
                )
                llm_summary_ok = True
                append_log(log_lines, log_placeholder, "LLM analysis completed.")
            except Exception as exc:
                llm_summary = f"LLM analysis failed: {exc}"
                append_log(log_lines, log_placeholder, llm_summary)
    elif llm_enabled and not llm_api_key:
        append_log(log_lines, log_placeholder, "LLM analysis skipped -> no API key configured.")

    report_path = write_run_report(output_base, routed_rows, results_by_platform, user_request, llm_summary)
    summary_path = write_llm_summary_file(output_base, routed_rows, user_request, llm_summary) if llm_summary_ok else None
    progress.progress(1.0, text="Workflow complete")

    st.divider()
    st.success(f"Workflow complete. Raw report saved to: {report_path}")
    if summary_path:
        st.success(f"LLM content summary saved to: {summary_path}")

    if llm_summary:
        st.markdown("### LLM Analysis")
        st.markdown(llm_summary)

    st.markdown("### Results")
    for platform, results in results_by_platform.items():
        ok_count = sum(1 for item in results if item.get("status") == "ok" or item.get("transcript_status") == "ok")
        st.markdown(f"**{PLATFORM_LABELS.get(platform, platform)}:** {ok_count}/{len(results)} item(s) completed")
        for item in results:
            status = item.get("status") or item.get("transcript_status") or "unknown"
            badge = "badge-ok" if status == "ok" else "badge-fail"
            title = item.get("title") or item.get("shortcode") or item.get("post_id") or item.get("url") or "Item"
            st.markdown(f'<span class="badge {badge}">{status}</span> {title}', unsafe_allow_html=True)
            if item.get("error"):
                st.error(item["error"])
            preview = item.get("caption") or item.get("transcript")
            if preview:
                with st.expander("Preview"):
                    st.text(str(preview)[:2000])
