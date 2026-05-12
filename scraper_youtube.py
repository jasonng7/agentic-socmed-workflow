import glob
import html
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from utils import format_number, get_output_dir


# ── Pure helpers ───────────────────────────────────────────────────────────────

def clean_transcript(text):
    """Remove YouTube censor placeholders and decode HTML entities."""
    text = html.unescape(text)
    text = re.sub(r"\[\s*_+\s*\]", "", text)
    text = re.sub(r"\[\s*&nbsp;_+&nbsp;\s*\]", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def clean_youtube_url(url):
    """Remove tracking parameters like ?si=, &t= timestamps."""
    url = url.strip()
    if "?" in url:
        base, query = url.split("?", 1)
        params = query.split("&")
        clean_params = [
            p for p in params
            if not any(p.startswith(prefix) for prefix in ["si=", "feature=", "utm_", "t="])
        ]
        if clean_params:
            url = f"{base}?{'&'.join(clean_params)}"
        else:
            url = base
    return url


def _ytdlp_cmd():
    """Return the best available yt-dlp command."""
    binary = shutil.which("yt-dlp")
    if binary:
        return [binary]
    return [sys.executable, "-m", "yt_dlp"]


def run_ytdlp(args, timeout=120, browser="None", cookies_file=None):
    """Run yt-dlp with de-restriction flags and cookie support."""
    cmd = _ytdlp_cmd()

    cmd += [
        "--remote-components", "ejs:github",
        "--extractor-args",
        "youtube:player-client=web_creator,web;player-skip=web_embedded,tv,ios",
    ]

    if cookies_file:
        cmd += ["--cookies", cookies_file]
    elif browser and browser != "None":
        cmd += ["--cookies-from-browser", browser.lower()]

    res = subprocess.run(cmd + args, capture_output=True, text=True, timeout=timeout)

    if res.returncode != 0 and "HTTP Error 429" in res.stderr:
        st.error("**YouTube Rate Limited (429: Too Many Requests)**")
        st.markdown(
            "YouTube has temporarily blocked requests from your IP address.\n\n"
            "**How to fix:**\n"
            "1. Upload a manual `cookies.txt` file in the sidebar\n"
            "2. Wait 15-30 minutes for the block to clear"
        )
        st.stop()

    if res.returncode != 0 and "Operation not permitted" in res.stderr:
        st.error(f"**macOS Permission Required: {browser}**")
        st.markdown(
            "Grant **Full Disk Access** to Terminal in System Settings, "
            "or use a manual cookies.txt file instead."
        )
        st.stop()

    return res


def safe_int(val):
    """Try to cast val to int; return None on failure."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def parse_vtt(filepath):
    """Parse a .vtt subtitle file into clean plain text."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    text_lines = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        if re.match(r"^\d{2}:\d{2}", line) or re.match(r"^\d+$", line):
            continue
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line:
            text_lines.append(line)
    deduped = []
    for line in text_lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return " ".join(deduped)


# ── Core functions ─────────────────────────────────────────────────────────────

def scrape_video_list(channel_url, max_videos, browser="None", cookies_file=None):
    """Fetch video metadata via yt-dlp flat-playlist."""
    channel_url = clean_youtube_url(channel_url)

    result = run_ytdlp(
        [
            "--flat-playlist",
            "--print",
            "%(id)s\t%(title)s\t%(duration)s\t%(upload_date)s\t%(view_count)s\t%(like_count)s\t%(webpage_url)s",
            "--no-warnings",
            "--ignore-errors",
            "--playlist-end", str(max_videos),
            channel_url,
        ],
        browser=browser,
        cookies_file=cookies_file,
    )

    raw_videos = []
    for line in result.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) >= 7:
            raw_videos.append(parts[:7])

    videos = []
    for vid_id, title, duration, upload_date, views, likes, url in raw_videos:
        is_short_url = "shorts" in url
        try:
            dur_sec = int(duration)
        except (ValueError, TypeError):
            dur_sec = None
        is_short = is_short_url or (dur_sec is not None and dur_sec <= 60)

        needs_full_fetch = (
            duration in ("NA", "None", "") or upload_date in ("NA", "None", "")
        ) and is_short
        if needs_full_fetch:
            short_url = f"https://www.youtube.com/shorts/{vid_id}"
            r2 = run_ytdlp(
                [
                    "--no-playlist",
                    "--print",
                    "%(duration)s\t%(upload_date)s\t%(view_count)s\t%(like_count)s",
                    "--no-warnings",
                    "--ignore-errors",
                    short_url,
                ],
                timeout=20,
                browser=browser,
                cookies_file=cookies_file,
            )
            line2 = r2.stdout.strip().splitlines()
            if line2:
                parts2 = line2[0].split("\t")
                if len(parts2) >= 4:
                    duration, upload_date, views, likes = parts2[:4]
                    try:
                        dur_sec = int(duration)
                    except (ValueError, TypeError):
                        dur_sec = None

        if dur_sec is not None:
            m, s = divmod(dur_sec, 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        else:
            dur_str = "N/A"

        try:
            upload_date_fmt = datetime.strptime(upload_date, "%Y%m%d").strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            upload_date_fmt = upload_date if upload_date not in ("NA", "None", "") else "N/A"

        final_url = url if url.startswith("http") else f"https://www.youtube.com/watch?v={vid_id}"
        if is_short:
            final_url = f"https://www.youtube.com/shorts/{vid_id}"

        def clean(val):
            return val if val not in ("NA", "None", "", "N/A") else "N/A"

        videos.append({
            "id": vid_id,
            "title": title,
            "url": final_url,
            "duration": dur_str,
            "duration_sec": dur_sec,
            "upload_date": upload_date_fmt,
            "views": clean(views),
            "likes": clean(likes),
            "is_short": is_short,
            "transcript": "",
            "transcript_status": "pending",
            "transcript_method": "",
        })
    return videos


def get_transcript(video_id, is_short=False, use_whisper=False,
                   browser="None", cookies_file=None):
    """Multi-method transcript extraction with fallback chain.
    Returns (text, status, method_used)."""
    urls_to_try = (
        [f"https://www.youtube.com/shorts/{video_id}", f"https://www.youtube.com/watch?v={video_id}"]
        if is_short
        else [f"https://www.youtube.com/watch?v={video_id}"]
    )

    # Method 1: youtube-transcript-api
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            entries = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
            text = clean_transcript(" ".join(e["text"] for e in entries))
            if text:
                return text, "ok", "api-en"
        except Exception:
            pass
        try:
            tlist = YouTubeTranscriptApi.list_transcripts(video_id)
            for t in tlist:
                try:
                    entries = t.fetch()
                    text = clean_transcript(" ".join(e["text"] for e in entries))
                    if text:
                        return text, "ok", f"api-{t.language_code}"
                except Exception:
                    continue
        except Exception:
            pass
    except Exception:
        pass

    # Methods 2-5: yt-dlp subtitle download
    with tempfile.TemporaryDirectory() as tmpdir:
        out_tmpl = os.path.join(tmpdir, "sub")
        sub_attempts = [
            ["--write-subs", "--sub-lang", "en"],
            ["--write-auto-subs", "--sub-lang", "en"],
            ["--write-auto-subs", "--sub-lang", "en-orig"],
            ["--write-subs", "--write-auto-subs", "--sub-lang", "en,en-US,en-GB,en-orig"],
            ["--write-auto-subs"],
        ]

        for url in urls_to_try:
            for sub_flags in sub_attempts:
                for f in glob.glob(os.path.join(tmpdir, "*")):
                    try:
                        os.remove(f)
                    except OSError:
                        pass

                run_ytdlp(
                    sub_flags + [
                        "--skip-download",
                        "--sub-format", "vtt",
                        "--convert-subs", "vtt",
                        "--output", out_tmpl,
                        "--no-warnings",
                        "--ignore-errors",
                        url,
                    ],
                    timeout=40,
                    browser=browser,
                    cookies_file=cookies_file,
                )
                vtt_files = glob.glob(os.path.join(tmpdir, "*.vtt"))
                if vtt_files:
                    chosen = next((f for f in vtt_files if ".en" in f), vtt_files[0])
                    text = clean_transcript(parse_vtt(chosen))
                    if text:
                        lang = os.path.basename(chosen).split(".")[-2] if "." in os.path.basename(chosen) else "?"
                        return text, "ok", f"ytdlp-{lang}"

    # Whisper fallback
    if use_whisper:
        from whisper_utils import extract_audio_with_ffmpeg, get_whisper_backend, transcribe_audio

        if get_whisper_backend() == "none":
            return "", "no-whisper", "whisper"

        urls_to_try_dl = (
            [f"https://www.youtube.com/shorts/{video_id}", f"https://www.youtube.com/watch?v={video_id}"]
            if is_short
            else [f"https://www.youtube.com/watch?v={video_id}"]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_tmpl = os.path.join(tmpdir, "audio.%(ext)s")
            audio_file = None

            for url in urls_to_try_dl:
                for f in glob.glob(os.path.join(tmpdir, "audio.*")):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
                run_ytdlp(
                    ["-x", "--output", audio_tmpl, "--no-warnings", url],
                    timeout=300,
                    browser=browser,
                    cookies_file=cookies_file,
                )
                found = glob.glob(os.path.join(tmpdir, "audio.*"))
                if found:
                    audio_file = found[0]
                    break

            if not audio_file:
                return "", "no-audio", "whisper"

            try:
                transcript, backend = transcribe_audio(audio_file)
                return (transcript, "ok", f"whisper-{backend}") if transcript else ("", "whisper-empty", f"whisper-{backend}")
            except Exception as exc:
                return "", f"whisper-error", "whisper"

    return "", "no transcript", "all failed"


def download_video_ytdlp(url, output_dir="downloads", browser="None",
                         cookies_file=None, quality="Best"):
    """Download video with quality selection."""
    os.makedirs(output_dir, exist_ok=True)
    outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

    args = ["--output", outtmpl, "--no-warnings", "--ignore-errors", url]

    if quality == "Audio Only (MP3)":
        args = ["-x", "--audio-format", "mp3"] + args
    elif quality == "Best":
        args = ["--format", "bestvideo+bestaudio/best"] + args
    else:
        res_limit = quality.split("p")[0].strip()
        args = ["--format", f"bestvideo[height<={res_limit}]+bestaudio/best[height<={res_limit}]"] + args

    return run_ytdlp(args, timeout=1200, browser=browser, cookies_file=cookies_file)


def filter_videos(videos, min_views, min_likes, min_dur_sec, max_dur_sec,
                  excl_na_views, excl_na_likes, excl_na_dur):
    """Return subset of videos that pass threshold checks."""
    result = []
    for v in videos:
        if min_views > 0:
            views_int = safe_int(v.get("views", "N/A"))
            if views_int is None:
                if excl_na_views:
                    continue
            elif views_int < min_views:
                continue

        if min_likes > 0:
            likes_int = safe_int(v.get("likes", "N/A"))
            if likes_int is None:
                if excl_na_likes:
                    continue
            elif likes_int < min_likes:
                continue

        dur_sec = v.get("duration_sec")
        if dur_sec is None:
            if excl_na_dur and (min_dur_sec > 0 or max_dur_sec > 0):
                continue
        else:
            if min_dur_sec > 0 and dur_sec < min_dur_sec:
                continue
            if max_dur_sec > 0 and dur_sec > max_dur_sec:
                continue

        result.append(v)
    return result


def build_excel(videos, filter_params=None):
    """Build styled 3-sheet Excel workbook. Returns BytesIO buffer."""
    wb = Workbook()

    header_fill = PatternFill("solid", start_color="1F4E79")
    header_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    cell_font = Font(name="Arial", size=9, color="1a1a1a")
    alt_fill = PatternFill("solid", start_color="EBF3FB")
    white_fill = PatternFill("solid", start_color="FFFFFF")
    thin_border = Border(bottom=Side(style="thin", color="D0D7DE"))

    # Sheet 1: All Videos
    ws = wb.active
    ws.title = "All Videos"
    headers = ["#", "Title", "Type", "URL", "Duration", "Upload Date",
               "Views", "Likes", "Transcript Status", "Method", "Transcript"]
    col_widths = [5, 40, 8, 45, 10, 13, 10, 10, 18, 14, 80]

    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22

    for i, v in enumerate(videos, 1):
        row = i + 1
        fill = alt_fill if i % 2 == 0 else white_fill
        values = [
            i, v["title"], "Short" if v["is_short"] else "Video",
            v["url"], v["duration"], v["upload_date"],
            v["views"], v["likes"], v["transcript_status"],
            v.get("transcript_method", ""), v["transcript"],
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.font = cell_font
            cell.fill = fill
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=(col == 11))
        ws.row_dimensions[row].height = 60 if v["transcript"] else 18

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    # Sheet 2: Transcripts only
    ws2 = wb.create_sheet("Transcripts")
    ws2_headers = ["#", "Title", "URL", "Upload Date", "Method", "Transcript"]
    ws2_widths = [5, 40, 45, 13, 14, 120]

    for col, (h, w) in enumerate(zip(ws2_headers, ws2_widths), 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
        ws2.column_dimensions[get_column_letter(col)].width = w
    ws2.row_dimensions[1].height = 22

    row2 = 2
    for i, v in enumerate(videos, 1):
        if not v["transcript"]:
            continue
        fill = alt_fill if i % 2 == 0 else white_fill
        for col, val in enumerate(
            [i, v["title"], v["url"], v["upload_date"],
             v.get("transcript_method", ""), v["transcript"]], 1
        ):
            cell = ws2.cell(row=row2, column=col, value=val)
            cell.font = cell_font
            cell.fill = fill
            cell.border = thin_border
            cell.alignment = Alignment(vertical="top", wrap_text=(col == 6))
        ws2.row_dimensions[row2].height = 80
        row2 += 1
    ws2.freeze_panes = "A2"

    # Sheet 3: Summary
    ws3 = wb.create_sheet("Summary")
    ws3.column_dimensions["A"].width = 32
    ws3.column_dimensions["B"].width = 22

    ok_count = sum(1 for v in videos if v["transcript_status"] == "ok")
    whisper_count = sum(
        1 for v in videos
        if v.get("transcript_method", "").startswith("whisper") and v["transcript_status"] == "ok"
    )

    summary_data = [
        ("Generated on", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Total Videos", len(videos)),
        ("Shorts", sum(1 for v in videos if v["is_short"])),
        ("Regular Videos", sum(1 for v in videos if not v["is_short"])),
        ("With Transcript", ok_count),
        ("Via Whisper Fallback", whisper_count),
        ("No Transcript", len(videos) - ok_count),
    ]

    if filter_params:
        summary_data += [
            ("-- Filters Applied --", ""),
            ("Min Views", filter_params.get("min_views", 0) or "--"),
            ("Min Likes", filter_params.get("min_likes", 0) or "--"),
            ("Min Duration", f"{filter_params.get('min_dur_min', 0):.1f} min" if filter_params.get("min_dur_min") else "--"),
            ("Max Duration", f"{filter_params.get('max_dur_min', 0):.1f} min" if filter_params.get("max_dur_min") else "--"),
        ]

    ws3["A1"].value = "YouTube Transcript Scraper -- Summary"
    ws3["A1"].font = Font(name="Arial", bold=True, color="FFFFFF", size=13)
    ws3.merge_cells("A1:B1")
    ws3["A1"].fill = PatternFill("solid", start_color="1F4E79")

    for r, (label, val) in enumerate(summary_data, 3):
        ws3.cell(row=r, column=1, value=label).font = Font(name="Arial", bold=True, color="1F4E79", size=10)
        ws3.cell(row=r, column=2, value=val).font = Font(name="Arial", size=10, color="1a1a1a")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def is_youtube_collection_url(url: str) -> bool:
    """Return True when a URL is likely a channel, handle, user, playlist, or videos page."""
    lowered = url.lower()
    return any(marker in lowered for marker in ["/@", "/channel/", "/c/", "/user/", "/playlist?", "/videos"])


def get_single_video_metadata(url: str, browser="None", cookies_file=None) -> dict:
    """Fetch metadata for one YouTube video via yt-dlp."""
    clean_url = clean_youtube_url(url)
    result = run_ytdlp(
        [
            "--no-playlist",
            "--skip-download",
            "--print",
            "%(id)s\t%(title)s\t%(duration)s\t%(upload_date)s\t%(view_count)s\t%(like_count)s\t%(webpage_url)s",
            "--no-warnings",
            "--ignore-errors",
            clean_url,
        ],
        browser=browser,
        cookies_file=cookies_file,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "yt-dlp returned no metadata")

    parts = result.stdout.strip().splitlines()[0].split("\t")
    if len(parts) < 7:
        raise RuntimeError(f"Unexpected yt-dlp metadata format: {result.stdout[:300]}")

    vid_id, title, duration, upload_date, views, likes, final_url = parts[:7]
    dur_sec = safe_int(duration)
    is_short = "shorts" in final_url or (dur_sec is not None and dur_sec <= 60)
    if dur_sec is not None:
        m, s = divmod(dur_sec, 60)
        h, m = divmod(m, 60)
        dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    else:
        dur_str = "N/A"

    try:
        upload_date_fmt = datetime.strptime(upload_date, "%Y%m%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        upload_date_fmt = upload_date if upload_date not in ("NA", "None", "") else "N/A"

    return {
        "id": vid_id,
        "title": title,
        "url": final_url if final_url.startswith("http") else clean_url,
        "duration": dur_str,
        "duration_sec": dur_sec,
        "upload_date": upload_date_fmt,
        "views": views if views not in ("NA", "None", "") else "N/A",
        "likes": likes if likes not in ("NA", "None", "") else "N/A",
        "is_short": is_short,
        "transcript": "",
        "transcript_status": "pending",
        "transcript_method": "",
    }


def process_youtube_urls(
    urls: list[str],
    output_dir,
    extract_metadata: bool = True,
    extract_transcript: bool = True,
    download_videos: bool = False,
    max_videos_per_collection: int = 20,
    filter_type: str = "All",
    browser: str = "None",
    cookies_file: str | None = None,
    use_whisper: bool = True,
    quality: str = "Best",
    progress_callback=None,
) -> list[dict]:
    """Process YouTube video, channel, playlist, and shorts URLs."""
    output_dir = str(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for i, raw_url in enumerate(urls):
        url = clean_youtube_url(raw_url)
        if progress_callback:
            progress_callback(i, len(urls), f"YouTube routing: {url[:70]}...")

        try:
            if is_youtube_collection_url(url):
                videos = scrape_video_list(
                    url,
                    max_videos_per_collection,
                    browser=browser,
                    cookies_file=cookies_file,
                )
            else:
                videos = [get_single_video_metadata(url, browser=browser, cookies_file=cookies_file)]

            if filter_type == "Shorts only":
                videos = [v for v in videos if v["is_short"]]
            elif filter_type == "Videos only":
                videos = [v for v in videos if not v["is_short"]]

            for v_index, video in enumerate(videos):
                if progress_callback:
                    progress_callback(
                        i,
                        len(urls),
                        f"YouTube item {v_index + 1}/{len(videos)}: {video['title'][:60]}...",
                    )

                if extract_transcript:
                    transcript, status, method = get_transcript(
                        video["id"],
                        is_short=video["is_short"],
                        use_whisper=use_whisper,
                        browser=browser,
                        cookies_file=cookies_file,
                    )
                    video["transcript"] = transcript
                    video["transcript_status"] = status
                    video["transcript_method"] = method

                    transcript_path = os.path.join(output_dir, f"{video['id']}_transcript.txt")
                    with open(transcript_path, "w", encoding="utf-8") as f:
                        f.write(transcript or "")
                    video["transcript_path"] = transcript_path

                if download_videos:
                    dl_result = download_video_ytdlp(
                        video["url"],
                        output_dir=output_dir,
                        browser=browser,
                        cookies_file=cookies_file,
                        quality=quality,
                    )
                    video["download_status"] = "ok" if dl_result.returncode == 0 else "error"
                    video["download_error"] = dl_result.stderr if dl_result.returncode != 0 else ""

                video["source_input_url"] = raw_url
                video["status"] = "ok"
                results.append(video)

            if extract_metadata and videos:
                excel_path = os.path.join(output_dir, f"youtube_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
                with open(excel_path, "wb") as f:
                    f.write(build_excel(videos).getvalue())
                for video in results[-len(videos):]:
                    video["excel_path"] = excel_path

        except Exception as exc:
            results.append({
                "source_input_url": raw_url,
                "url": url,
                "platform": "youtube",
                "status": "error",
                "error": str(exc),
                "transcript": "",
            })

    return results


# ── Streamlit UI ───────────────────────────────────────────────────────────────

_yt_defaults = {
    "yt_metadata_videos": [],
    "yt_metadata_done": False,
    "yt_filter_previewed": False,
    "yt_filtered_for_preview": [],
    "yt_transcripts_done": False,
    "yt_final_videos": [],
    "yt_excel_buf": None,
}


def render_youtube_sidebar() -> dict:
    """Render YouTube-specific sidebar controls."""
    for _k, _v in _yt_defaults.items():
        if _k not in st.session_state:
            st.session_state[_k] = _v

    is_linux = platform.system() == "Linux"
    default_browser_idx = 4 if is_linux else 1  # "None" on Linux, "Chrome" otherwise

    with st.sidebar:
        st.markdown("### YouTube Settings")
        channel_url = st.text_input("Channel / Playlist URL",
                                     placeholder="https://youtube.com/@channelname")
        max_videos = st.number_input("Max videos to fetch", min_value=1, max_value=500, value=20)
        filter_type = st.selectbox("Filter by type", ["All", "Shorts only", "Videos only"])

        st.divider()
        st.markdown("### Cookie Settings")
        browser_choice = st.selectbox(
            "Browser for cookies",
            ["Safari", "Chrome", "Firefox", "Edge", "None"],
            index=default_browser_idx,
            help="Uses browser cookies to bypass YouTube bot detection.",
        )

        cookies_path_input = st.text_input(
            "Manual Cookies File (.txt)",
            value="",
            placeholder="e.g. /path/to/cookies.txt",
            help="Path to a cookies.txt file exported from your browser.",
        ).strip()

        cookies_final = cookies_path_input if cookies_path_input else None

        if is_linux and browser_choice != "None":
            st.warning("On VPS/Linux, use a manual cookies.txt file instead of browser cookies.")

        uploaded_cookies = st.file_uploader("Or upload cookies.txt", type=["txt"])
        if uploaded_cookies:
            dl_dir = get_output_dir("youtube")
            cookies_path = dl_dir / "cookies.txt"
            cookies_path.write_bytes(uploaded_cookies.getvalue())
            cookies_final = str(cookies_path)
            st.success(f"Using uploaded cookies: {uploaded_cookies.name}")

        st.divider()
        st.markdown("### Video Quality")
        quality_choice = st.selectbox(
            "Preferred Quality",
            ["Best", "2160p (4K)", "1080p (HD)", "720p", "480p", "Audio Only (MP3)"],
            index=0,
        )

        st.divider()
        fetch_btn = st.button("Fetch Metadata", use_container_width=True)

        if st.session_state.yt_metadata_done:
            if st.button("Start Over", use_container_width=True):
                for k in list(_yt_defaults.keys()):
                    st.session_state[k] = _yt_defaults[k]
                st.rerun()

        st.divider()
        st.markdown("### Whisper Fallback")
        use_whisper = st.checkbox(
            "Enable Whisper fallback",
            value=True,
            help="When captions aren't available, download audio and transcribe locally.",
        )
        if use_whisper:
            from whisper_utils import get_whisper_info
            st.info(get_whisper_info())

    return {
        "channel_url": channel_url,
        "max_videos": max_videos,
        "filter_type": filter_type,
        "browser_choice": browser_choice,
        "cookies_final": cookies_final,
        "quality_choice": quality_choice,
        "fetch_btn": fetch_btn,
        "use_whisper": use_whisper,
    }


def render_youtube_ui(config: dict) -> None:
    """Render the YouTube interface in the main area."""
    channel_url = config["channel_url"]
    max_videos = config["max_videos"]
    filter_type = config["filter_type"]
    browser_choice = config["browser_choice"]
    cookies_final = config["cookies_final"]
    quality_choice = config["quality_choice"]
    fetch_btn = config["fetch_btn"]
    use_whisper = config["use_whisper"]

    st.markdown("## YouTube Content Tool")

    tab_scraper, tab_downloader = st.tabs(["Transcript Scraper", "Video Downloader"])

    # ── Phase indicator ─────────────────────────────────────────────────────
    with tab_scraper:
        phase_icons = ["Metadata", "Filter", "Extract", "Results"]
        phase_idx = (
            3 if st.session_state.yt_transcripts_done
            else 1 if st.session_state.yt_metadata_done
            else 0
        )
        cols = st.columns(4)
        for i, (col, label) in enumerate(zip(cols, phase_icons)):
            active = i == phase_idx
            col.markdown(
                f'<div style="text-align:center;padding:6px 0;border-radius:8px;'
                f'background:{"#1e3a2e" if active else "#18181c"};'
                f'border:1px solid {"#6ee7b7" if active else "#2a2a30"};'
                f'color:{"#6ee7b7" if active else "#4b5563"};font-size:0.75rem;font-weight:600">'
                f'{label}</div>',
                unsafe_allow_html=True,
            )
        st.divider()

        # ── Phase 1: Fetch metadata ─────────────────────────────────────────
        if fetch_btn:
            if not channel_url:
                st.error("Please enter a YouTube channel or playlist URL.")
            else:
                for k in ["yt_metadata_done", "yt_filter_previewed", "yt_transcripts_done",
                          "yt_final_videos", "yt_excel_buf"]:
                    st.session_state[k] = _yt_defaults[k]

                with st.spinner("Fetching video metadata..."):
                    try:
                        videos = scrape_video_list(
                            channel_url, max_videos,
                            browser=browser_choice, cookies_file=cookies_final,
                        )
                    except Exception as e:
                        st.error(f"Failed to fetch metadata: {e}")
                        st.stop()

                if not videos:
                    st.warning("No videos found. Check the URL and try again.")
                    st.stop()

                if filter_type == "Shorts only":
                    videos = [v for v in videos if v["is_short"]]
                elif filter_type == "Videos only":
                    videos = [v for v in videos if not v["is_short"]]

                st.session_state.yt_metadata_videos = videos
                st.session_state.yt_metadata_done = True
                st.success(f"Fetched metadata for **{len(videos)} videos**. Set filters below, then extract.")

        # ── Phase 2: Filters ────────────────────────────────────────────────
        if st.session_state.yt_metadata_done and not st.session_state.yt_transcripts_done:
            videos = st.session_state.yt_metadata_videos

            shorts = sum(1 for v in videos if v["is_short"])
            views_list = [safe_int(v["views"]) for v in videos]
            views_list = [x for x in views_list if x is not None]
            avg_views = int(sum(views_list) / len(views_list)) if views_list else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f'<div class="stat-card"><div class="stat-number">{len(videos)}</div><div class="stat-label">Total Videos</div></div>', unsafe_allow_html=True)
            c2.markdown(f'<div class="stat-card"><div class="stat-number">{shorts}</div><div class="stat-label">Shorts</div></div>', unsafe_allow_html=True)
            c3.markdown(f'<div class="stat-card"><div class="stat-number">{len(videos) - shorts}</div><div class="stat-label">Regular Videos</div></div>', unsafe_allow_html=True)
            c4.markdown(f'<div class="stat-card"><div class="stat-number">{format_number(str(avg_views))}</div><div class="stat-label">Avg Views</div></div>', unsafe_allow_html=True)

            st.divider()

            with st.expander("Filter Thresholds", expanded=True):
                fc1, fc2, fc3 = st.columns(3)

                with fc1:
                    st.markdown("**Views**")
                    min_views = int(st.number_input(
                        "Minimum views", min_value=0, value=0, step=1000,
                        key="f_min_views", label_visibility="collapsed",
                    ))
                    excl_na_views = st.checkbox("Exclude N/A views", key="f_excl_views")

                with fc2:
                    st.markdown("**Likes**")
                    min_likes = int(st.number_input(
                        "Minimum likes", min_value=0, value=0, step=100,
                        key="f_min_likes", label_visibility="collapsed",
                    ))
                    excl_na_likes = st.checkbox("Exclude N/A likes", key="f_excl_likes")

                with fc3:
                    st.markdown("**Duration (minutes)**")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        min_dur_min = st.number_input("Min", min_value=0.0, value=0.0,
                                                       step=0.5, key="f_min_dur", format="%.1f")
                    with dc2:
                        max_dur_min = st.number_input("Max (0 = inf)", min_value=0.0, value=0.0,
                                                       step=0.5, key="f_max_dur", format="%.1f")
                    excl_na_dur = st.checkbox("Exclude N/A duration", key="f_excl_dur")

                min_dur_sec = int(min_dur_min * 60)
                max_dur_sec = int(max_dur_min * 60)

                filtered = filter_videos(
                    videos, min_views, min_likes, min_dur_sec, max_dur_sec,
                    excl_na_views, excl_na_likes, excl_na_dur,
                )
                dropped = len(videos) - len(filtered)

                if dropped > 0:
                    st.info(f"**{len(filtered)} of {len(videos)}** videos pass -- {dropped} filtered out.")
                else:
                    st.info(f"**All {len(videos)} videos** pass (no active filters).")

                btn_c1, btn_c2 = st.columns(2)
                preview_btn = btn_c1.button(
                    f"Preview Filtered ({len(filtered)})",
                    use_container_width=True, disabled=(len(filtered) == 0),
                )
                extract_btn = btn_c2.button(
                    f"Extract Transcripts ({len(filtered)})",
                    use_container_width=True, disabled=(len(filtered) == 0),
                )

                if preview_btn:
                    st.session_state.yt_filtered_for_preview = filtered
                    st.session_state.yt_filter_previewed = True

            if st.session_state.yt_filter_previewed and not extract_btn:
                st.markdown(f"### Preview -- {len(st.session_state.yt_filtered_for_preview)} videos")
                for v in st.session_state.yt_filtered_for_preview:
                    badge_type = "badge-short" if v["is_short"] else "badge-video"
                    type_label = "Short" if v["is_short"] else "Video"
                    views_fmt = format_number(v["views"])
                    likes_fmt = format_number(v["likes"])
                    st.markdown(
                        f'<div class="video-row">'
                        f'<div class="video-title"><span class="badge {badge_type}">{type_label}</span> {v["title"]}</div>'
                        f'<div class="video-meta">'
                        f'{v["duration"]} &nbsp;|&nbsp; {v["upload_date"]} &nbsp;|&nbsp; '
                        f'{views_fmt} views &nbsp;|&nbsp; {likes_fmt} likes &nbsp;|&nbsp; '
                        f'<a href="{v["url"]}" style="color:#6ee7b7" target="_blank">Open</a>'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )

            # ── Phase 3: Extract ────────────────────────────────────────────
            if extract_btn and len(filtered) > 0:
                st.divider()
                st.markdown("### Extracting Transcripts")

                ec1, ec2, ec3, ec4 = st.columns(4)
                stat_phs = {
                    "total": ec1.empty(), "ok": ec2.empty(),
                    "fail": ec3.empty(), "whisper": ec4.empty(),
                }

                def update_stats(vids):
                    ok_n = sum(1 for v in vids if v["transcript_status"] == "ok")
                    fail_n = sum(1 for v in vids if v["transcript_status"] not in ("ok", "pending"))
                    whisper_n = sum(1 for v in vids if v.get("transcript_method", "").startswith("whisper") and v["transcript_status"] == "ok")
                    stat_phs["total"].markdown(f'<div class="stat-card"><div class="stat-number">{len(vids)}</div><div class="stat-label">Total</div></div>', unsafe_allow_html=True)
                    stat_phs["ok"].markdown(f'<div class="stat-card"><div class="stat-number" style="color:#6ee7b7">{ok_n}</div><div class="stat-label">Got Transcript</div></div>', unsafe_allow_html=True)
                    stat_phs["fail"].markdown(f'<div class="stat-card"><div class="stat-number" style="color:#f87171">{fail_n}</div><div class="stat-label">No Transcript</div></div>', unsafe_allow_html=True)
                    stat_phs["whisper"].markdown(f'<div class="stat-card"><div class="stat-number" style="color:#fbbf24">{whisper_n}</div><div class="stat-label">Via Whisper</div></div>', unsafe_allow_html=True)

                update_stats(filtered)

                progress_bar = st.progress(0, text="Starting...")
                log_placeholder = st.empty()
                log_lines = []

                for i, v in enumerate(filtered):
                    progress_bar.progress(
                        i / len(filtered),
                        text=f"[{i + 1}/{len(filtered)}] {v['title'][:55]}...",
                    )
                    transcript, status, method = get_transcript(
                        v["id"], is_short=v["is_short"], use_whisper=use_whisper,
                        browser=browser_choice, cookies_file=cookies_final,
                    )
                    v["transcript"] = transcript
                    v["transcript_status"] = status
                    v["transcript_method"] = method

                    icon = "+" if status == "ok" else "x"
                    whisper_tag = " [whisper]" if method.startswith("whisper") else ""
                    log_lines.append(f"{icon} [{i + 1}/{len(filtered)}] {v['title'][:50]} [{method}]{whisper_tag}")
                    log_placeholder.markdown(
                        '<div class="log-box">' + "<br>".join(log_lines[-10:]) + "</div>",
                        unsafe_allow_html=True,
                    )
                    update_stats(filtered)

                progress_bar.progress(1.0, text="Done!")

                st.session_state.yt_final_videos = filtered
                st.session_state.yt_transcripts_done = True
                st.session_state.yt_excel_buf = build_excel(filtered, {
                    "min_views": min_views, "min_likes": min_likes,
                    "min_dur_min": min_dur_min, "max_dur_min": max_dur_min,
                })
                st.rerun()

        # ── Phase 4: Results ────────────────────────────────────────────────
        if st.session_state.yt_transcripts_done and st.session_state.yt_final_videos:
            videos = st.session_state.yt_final_videos
            ok_count = sum(1 for v in videos if v["transcript_status"] == "ok")
            fail_count = len(videos) - ok_count
            whisper_count = sum(
                1 for v in videos
                if v.get("transcript_method", "").startswith("whisper") and v["transcript_status"] == "ok"
            )

            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.markdown(f'<div class="stat-card"><div class="stat-number">{len(videos)}</div><div class="stat-label">Processed</div></div>', unsafe_allow_html=True)
            rc2.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#6ee7b7">{ok_count}</div><div class="stat-label">Got Transcript</div></div>', unsafe_allow_html=True)
            rc3.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#f87171">{fail_count}</div><div class="stat-label">No Transcript</div></div>', unsafe_allow_html=True)
            rc4.markdown(f'<div class="stat-card"><div class="stat-number" style="color:#fbbf24">{whisper_count}</div><div class="stat-label">Via Whisper</div></div>', unsafe_allow_html=True)

            st.markdown("")
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button(
                label="Download Excel",
                data=st.session_state.yt_excel_buf,
                file_name=f"yt_transcripts_{ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            st.divider()

            for v in videos:
                badge_type = "badge-short" if v["is_short"] else "badge-video"
                type_label = "Short" if v["is_short"] else "Video"
                is_whisper = v.get("transcript_method", "").startswith("whisper")
                status_badge = "badge-whisper" if is_whisper else ("badge-ok" if v["transcript_status"] == "ok" else "badge-fail")
                method_label = v.get("transcript_method", "") or "?"
                status_label = (
                    f"[whisper] {method_label}" if is_whisper
                    else (f"[ok] {method_label}" if v["transcript_status"] == "ok" else "[fail] no transcript")
                )
                views_fmt = format_number(v["views"])
                likes_fmt = format_number(v["likes"])

                with st.container():
                    col_info, col_dl = st.columns([0.82, 0.18])

                    with col_info:
                        transcript_preview = ""
                        if v["transcript"]:
                            preview_text = v["transcript"][:200]
                            ellipsis = "..." if len(v["transcript"]) > 200 else ""
                            transcript_preview = (
                                f'<div class="video-meta" style="margin-top:6px;color:#9ca3af;">'
                                f'{preview_text}{ellipsis}</div>'
                            )
                        st.markdown(
                            f'<div class="video-row" style="margin-bottom:0px;border-bottom:none;'
                            f'border-bottom-left-radius:0px;border-bottom-right-radius:0px;">'
                            f'<div class="video-title">'
                            f'<span class="badge {badge_type}">{type_label}</span>'
                            f'<span class="badge {status_badge}">{status_label}</span>'
                            f' {v["title"]}</div>'
                            f'<div class="video-meta">'
                            f'{v["duration"]} &nbsp;|&nbsp; {v["upload_date"]} &nbsp;|&nbsp; '
                            f'{views_fmt} views &nbsp;|&nbsp; {likes_fmt} likes &nbsp;|&nbsp; '
                            f'<a href="{v["url"]}" style="color:#6ee7b7" target="_blank">Open</a></div>'
                            f'{transcript_preview}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                    with col_dl:
                        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
                        if st.button("Download", key=f"dl_{v['id']}", use_container_width=True):
                            with st.spinner("Downloading..."):
                                dl_dir = get_output_dir("youtube", config.get("output_base", "./downloads"))
                                res = download_video_ytdlp(
                                    v["url"], output_dir=str(dl_dir),
                                    browser=browser_choice, cookies_file=cookies_final,
                                    quality=quality_choice,
                                )
                                if res.returncode == 0:
                                    st.toast(f"Downloaded: {v['title']}")
                                else:
                                    st.error("Download failed. Check permissions or try a different cookie source.")

                    st.markdown(
                        '<div style="height:8px;background:#18181c;border:1px solid #2a2a30;border-top:none;'
                        'border-bottom-left-radius:10px;border-bottom-right-radius:10px;margin-bottom:8px;"></div>',
                        unsafe_allow_html=True,
                    )

    # ── Tab 2: Standalone Video Downloader ──────────────────────────────────
    with tab_downloader:
        st.markdown("### Standalone Video Downloader")
        st.info("Paste one or more YouTube links below (one per line) to download them.")

        url_text = st.text_area(
            "YouTube URLs",
            placeholder="https://youtu.be/...\nhttps://youtube.com/watch?v=...",
            height=200,
        )

        col_dl_btn, col_dl_info = st.columns([0.3, 0.7])
        batch_dl_btn = col_dl_btn.button("Start Batch Download", use_container_width=True)

        if batch_dl_btn:
            urls = [u.strip() for u in url_text.split("\n") if u.strip()]
            if not urls:
                st.warning("Please paste at least one valid URL.")
            else:
                st.divider()
                st.markdown(f"**Processing Batch:** {len(urls)} videos")

                dl_progress = st.progress(0, text="Initializing...")
                dl_log_placeholder = st.empty()
                dl_logs = []

                dl_dir = get_output_dir("youtube", config.get("output_base", "./downloads"))

                for i, raw_url in enumerate(urls):
                    clean_url = clean_youtube_url(raw_url)
                    dl_progress.progress(
                        i / len(urls),
                        text=f"[{i + 1}/{len(urls)}] Processing...",
                    )

                    with st.spinner(f"Fetching metadata for {i + 1}/{len(urls)}..."):
                        try:
                            meta_res = run_ytdlp(
                                ["--get-title", "--get-id", clean_url],
                                browser=browser_choice, cookies_file=cookies_final,
                            )
                            if meta_res.returncode == 0:
                                meta_lines = meta_res.stdout.strip().split("\n")
                                title = meta_lines[0] if meta_lines else "Unknown Video"
                            else:
                                title = f"URL #{i + 1}"
                        except Exception:
                            title = f"URL #{i + 1}"

                    dl_logs.append(f"[{i + 1}/{len(urls)}] Downloading: **{title}**")
                    dl_log_placeholder.markdown(
                        '<div class="log-box">' + "<br>".join(dl_logs) + "</div>",
                        unsafe_allow_html=True,
                    )

                    res = download_video_ytdlp(
                        clean_url, output_dir=str(dl_dir),
                        browser=browser_choice, cookies_file=cookies_final,
                        quality=quality_choice,
                    )

                    if res.returncode == 0:
                        dl_logs[-1] = f"[{i + 1}/{len(urls)}] **{title}** -- Done!"
                    else:
                        dl_logs[-1] = f"[{i + 1}/{len(urls)}] **{title}** -- Failed"

                    dl_log_placeholder.markdown(
                        '<div class="log-box">' + "<br>".join(dl_logs) + "</div>",
                        unsafe_allow_html=True,
                    )

                dl_progress.progress(1.0, text="Batch complete!")
                st.success(f"Processed {len(urls)} URLs. Check your downloads folder!")
