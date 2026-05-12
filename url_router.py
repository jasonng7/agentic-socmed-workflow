import re
from dataclasses import dataclass
from urllib.parse import urlparse


URL_PATTERN = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)


@dataclass(frozen=True)
class RoutedUrl:
    original_url: str
    resolved_url: str
    platform: str
    reason: str
    error: str | None = None


def extract_urls(text: str) -> list[str]:
    """Extract unique URLs from free-form text while preserving order."""
    seen = set()
    urls = []
    for match in URL_PATTERN.finditer(text or ""):
        url = match.group(0).rstrip(".,;]")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def resolve_url(url: str, timeout: int = 10) -> tuple[str, str | None]:
    """Resolve redirects for short links. Returns (final_url, error)."""
    try:
        import requests

        response = requests.head(url, allow_redirects=True, timeout=timeout)
        if response.status_code >= 400 or response.url == url:
            response = requests.get(url, allow_redirects=True, timeout=timeout, stream=True)
        return response.url or url, None
    except Exception as exc:
        return url, str(exc)


def detect_platform(url: str) -> tuple[str, str]:
    """Detect supported platform from URL domain and path."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    path = parsed.path.lower()

    if host in {"instagram.com", "instagr.am"} or host.endswith(".instagram.com"):
        return "instagram", "Matched Instagram domain"

    if host in {"youtube.com", "youtu.be", "youtube-nocookie.com"} or host.endswith(".youtube.com"):
        return "youtube", "Matched YouTube domain"

    xhs_hosts = {"xiaohongshu.com", "xhslink.com", "xhs.cn"}
    if host in xhs_hosts or host.endswith(".xiaohongshu.com"):
        return "xhs", "Matched Xiaohongshu/RedNote domain"

    if "instagram" in host:
        return "instagram", "Matched Instagram-like host"
    if "youtube" in host or path.startswith("/shorts/"):
        return "youtube", "Matched YouTube-like host/path"
    if "xiaohongshu" in host or "xhs" in host:
        return "xhs", "Matched Xiaohongshu/RedNote-like host"

    return "unsupported", "No supported platform pattern matched"


def should_resolve_redirect(url: str) -> bool:
    """Resolve only short-link or unknown URLs to avoid captcha/login redirects."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.").removeprefix("m.")
    short_hosts = {
        "youtu.be",
        "xhslink.com",
        "xhs.cn",
        "instagr.am",
        "bit.ly",
        "tinyurl.com",
        "t.co",
        "lnkd.in",
        "shorturl.at",
    }
    if host in short_hosts:
        return True
    platform, _reason = detect_platform(url)
    return platform == "unsupported"


def route_urls(urls: list[str], resolve_redirects: bool = False) -> list[RoutedUrl]:
    """Classify URLs into supported platform buckets."""
    routed = []
    for url in urls:
        resolved = url
        resolve_error = None
        if resolve_redirects and should_resolve_redirect(url):
            resolved, resolve_error = resolve_url(url)
        platform, reason = detect_platform(resolved)
        routed.append(
            RoutedUrl(
                original_url=url,
                resolved_url=resolved,
                platform=platform,
                reason=reason,
                error=resolve_error,
            )
        )
    return routed


def group_routed_urls(routed: list[RoutedUrl]) -> dict[str, list[str]]:
    """Return platform -> resolved URL list for supported routes."""
    grouped: dict[str, list[str]] = {"instagram": [], "youtube": [], "xhs": []}
    for item in routed:
        if item.platform in grouped:
            grouped[item.platform].append(item.resolved_url)
    return grouped
