export type Platform = "instagram" | "youtube" | "xhs" | "unsupported";

export type RoutedUrl = {
  originalUrl: string;
  platform: Platform;
  label: string;
  reason: string;
};

const urlPattern = /https?:\/\/[^\s<>()"']+/gi;

export function extractUrls(input: string): string[] {
  const seen = new Set<string>();
  const urls: string[] = [];
  for (const match of input.matchAll(urlPattern)) {
    const url = match[0].replace(/[.,;\]]+$/g, "");
    if (!seen.has(url)) {
      seen.add(url);
      urls.push(url);
    }
  }
  return urls;
}

export function detectPlatform(url: string): Omit<RoutedUrl, "originalUrl"> {
  let host = "";
  let path = "";
  try {
    const parsed = new URL(url);
    host = parsed.hostname.toLowerCase().replace(/^www\./, "").replace(/^m\./, "");
    path = parsed.pathname.toLowerCase();
  } catch {
    return {
      platform: "unsupported",
      label: "Unsupported",
      reason: "Invalid URL"
    };
  }

  if (host === "instagram.com" || host === "instagr.am" || host.endsWith(".instagram.com")) {
    return { platform: "instagram", label: "Instagram", reason: "Matched Instagram domain" };
  }

  if (host === "youtube.com" || host === "youtu.be" || host.endsWith(".youtube.com")) {
    return { platform: "youtube", label: "YouTube", reason: "Matched YouTube domain" };
  }

  if (host === "xiaohongshu.com" || host === "xhslink.com" || host === "xhs.cn" || host.endsWith(".xiaohongshu.com")) {
    return { platform: "xhs", label: "RedNote / Xiaohongshu", reason: "Matched RedNote/Xiaohongshu domain" };
  }

  if (host.includes("instagram")) {
    return { platform: "instagram", label: "Instagram", reason: "Matched Instagram-like host" };
  }

  if (host.includes("youtube") || path.startsWith("/shorts/")) {
    return { platform: "youtube", label: "YouTube", reason: "Matched YouTube-like host/path" };
  }

  if (host.includes("xiaohongshu") || host.includes("xhs")) {
    return { platform: "xhs", label: "RedNote / Xiaohongshu", reason: "Matched RedNote/Xiaohongshu-like host" };
  }

  return {
    platform: "unsupported",
    label: "Unsupported",
    reason: "No supported platform pattern matched"
  };
}

export function routeInput(input: string): RoutedUrl[] {
  return extractUrls(input).map((originalUrl) => ({
    originalUrl,
    ...detectPlatform(originalUrl)
  }));
}
