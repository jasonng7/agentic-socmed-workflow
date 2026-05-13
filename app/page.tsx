"use client";

import { useEffect, useMemo, useState } from "react";
import { routeInput, RoutedUrl } from "@/lib/router";

type AnalyzeResponse = {
  summary?: string;
  results?: unknown;
  routes?: unknown;
  error?: string;
  details?: unknown;
};

type ExtractedItem = {
  key: string;
  platform: string;
  label: string;
  url: string;
  transcript: string;
  caption: string;
  transcriptStatus: string;
  metadataStatus: string;
};

export default function Home() {
  const [input, setInput] = useState("");
  const [preference, setPreference] = useState("");
  const [summaries, setSummaries] = useState<Record<string, string>>({});
  const [backendJson, setBackendJson] = useState("");
  const [extractionResults, setExtractionResults] = useState<unknown>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const routes = useMemo(() => routeInput(input), [input]);
  const supported = routes.filter((route) => route.platform !== "unsupported");
  const unsupported = routes.filter((route) => route.platform === "unsupported");
  const loadingSteps = useMemo(
    () => [
      "Routing links by platform",
      "Calling EC2 extraction backend through Vercel",
      "Extracting captions, transcripts, and metadata",
      "Returning JSON results"
    ],
    []
  );
  const activeStep = loading ? Math.min(Math.floor(elapsedSeconds / 12), loadingSteps.length - 1) : -1;
  const publicBackendUrl = (process.env.NEXT_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
  const extractedItems = useMemo(() => extractItems(extractionResults), [extractionResults]);
  const selectedItem = extractedItems[selectedIndex] || null;
  const selectedSummary = selectedItem ? summaries[selectedItem.key] || "" : "";

  useEffect(() => {
    if (!loading || !startedAt) {
      return;
    }
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [loading, startedAt]);

  async function extract() {
    setLoading(true);
    setStartedAt(Date.now());
    setElapsedSeconds(0);
    setError("");
    setSummaries({});
    setBackendJson("");
    setExtractionResults(null);
    setSelectedIndex(0);

    const endpoint = "/api/extract";
    const body = {
      input,
      user_preference: preference,
      summarize: false,
      resolve_redirects: true,
      include_instagram_caption: true,
      include_instagram_transcript: true,
      include_youtube_metadata: true,
      include_youtube_transcript: true,
      include_xhs_caption: true,
      max_videos_per_collection: 5,
      use_whisper: true
    };

    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
    } catch {
      setError("Could not reach the backend through Vercel. Check that EC2 is running and BACKEND_URL is correct.");
      setLoading(false);
      setStartedAt(null);
      return;
    }

    const data = (await response.json()) as AnalyzeResponse;
    if (!response.ok || data.error) {
      setError(data.error || "Analysis failed.");
      setLoading(false);
      setStartedAt(null);
      return;
    }

    const extractedPayload = {
      routes: data.routes,
      results: data.results
    };
    setExtractionResults(extractedPayload);
    setBackendJson(JSON.stringify(extractedPayload, null, 2));
    setLoading(false);
    setStartedAt(null);
  }

  async function summarizeExtractedContent() {
    if (!selectedItem) {
      setError("Extract content first, then summarize the generated output.");
      return;
    }

    setSummarizing(true);
    setError("");

    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input,
        userPreference: preference.trim() || "Summarize the extracted video transcript clearly and concisely. Use captions only as supporting context if the transcript is missing or unclear.",
        extractionJson: selectedItem
      })
    });

    const data = (await response.json()) as AnalyzeResponse;
    if (!response.ok || data.error) {
      setError(data.error || "Summary failed.");
      setSummarizing(false);
      return;
    }

    setSummaries((current) => ({
      ...current,
      [selectedItem.key]: data.summary || "No summary returned."
    }));
    setSummarizing(false);
  }

  function downloadText(filename: string, content: string, type = "text/plain;charset=utf-8") {
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  function csvCell(value: string) {
    return `"${value.replace(/"/g, '""')}"`;
  }

  function transcriptCsv(items: ExtractedItem[]) {
    const rows = [
      ["Platform", "Title", "URL", "Transcript Status", "Transcript", "Caption", "Summary"],
      ...items.map((item) => [
        item.platform,
        item.label,
        item.url,
        item.transcriptStatus,
        item.transcript,
        item.caption,
        summaries[item.key] || ""
      ])
    ];
    return rows.map((row) => row.map(csvCell).join(",")).join("\n");
  }

  function safeFilename(name: string, fallback: string) {
    const cleaned = name.replace(/[^a-z0-9-_ ]/gi, " ").replace(/\s+/g, " ").trim();
    return (cleaned || fallback).slice(0, 80);
  }

  function routeCard(route: RoutedUrl) {
    return (
      <div className="route" key={route.originalUrl}>
        <span className={`badge ${route.platform}`}>{route.label}</span>
        <p>{route.reason}</p>
        <p className="meta">{route.originalUrl}</p>
      </div>
    );
  }

  function extractItems(payload: unknown): ExtractedItem[] {
    const source = payload && typeof payload === "object" && "results" in payload
      ? (payload as { results?: unknown }).results
      : payload;
    if (!source || typeof source !== "object") {
      return [];
    }

    const items: ExtractedItem[] = [];
    const grouped = source as Record<string, unknown>;
    for (const [platform, value] of Object.entries(grouped)) {
      if (!Array.isArray(value)) {
        continue;
      }
      value.forEach((item, index) => {
        if (!item || typeof item !== "object") {
          return;
        }
        const record = item as Record<string, unknown>;
        const url = String(record.url || record.source_input_url || "");
        const label = String(record.title || record.shortcode || record.post_id || `${platform} ${index + 1}`);
        const rawTranscript = typeof record.transcript === "string" ? record.transcript.trim() : "";
        const rawCaption = typeof record.caption === "string" ? record.caption.trim() : "";
        items.push({
          key: `${platform}-${index}-${url || label}`,
          platform,
          label,
          url,
          transcript: rawTranscript.startsWith("[Transcription error") ? "" : rawTranscript,
          caption: rawCaption.startsWith("[Error") ? "" : rawCaption,
          transcriptStatus: String(record.transcript_status || record.status || ""),
          metadataStatus: String(record.metadata_status || record.status || "")
        });
      });
    }
    return items;
  }

  function downloadVideoUrl(url: string) {
    if (!publicBackendUrl) {
      return "";
    }
    return `${publicBackendUrl}/download-video?url=${encodeURIComponent(url)}`;
  }

  return (
    <main className="shell">
      <aside className="sidebar stack">
        <div className="stack">
          <p className="kicker">Vercel Frontend</p>
          <h1>Agentic Socmed Workflow</h1>
          <p className="meta">
            JSON-first interface for routing links, calling the Python backend, and summarizing transcript/caption data.
          </p>
        </div>

      </aside>

      <section className="main stack">
        <div className="header">
          <div className="stack">
            <p className="kicker">Step 1</p>
            <h1>Paste Links</h1>
          </div>
          <div className="actions">
            <button onClick={extract} disabled={loading || summarizing}>
              {loading ? "Extracting..." : "Extract Content"}
            </button>
          </div>
        </div>

        <div className="grid">
          <label className="stack">
            <span className="label">Input links or text containing links</span>
            <textarea
              rows={8}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Paste Instagram, YouTube, or RedNote/Xiaohongshu links here."
            />
          </label>

          <label className="stack">
            <span className="label">What should the LLM focus on?</span>
            <textarea
              rows={8}
              value={preference}
              onChange={(event) => setPreference(event.target.value)}
              placeholder="Type your exact summary request here. Leave blank for a default summary."
            />
          </label>
        </div>

        <div className="panel stack">
          <h2>Detected Routes</h2>
          {routes.length === 0 ? <p className="meta">No URLs detected yet.</p> : <div className="grid">{routes.map(routeCard)}</div>}
          {unsupported.length > 0 ? <p className="error">{unsupported.length} unsupported URL(s) detected.</p> : null}
          {supported.length > 0 ? <p className="meta">{supported.length} supported URL(s) ready for the backend workflow.</p> : null}
        </div>

        {error ? <div className="panel error">{error}</div> : null}

        {loading ? (
          <div className="panel stack">
            <div className="statusHeader">
              <div>
                <h2>Working On Extraction</h2>
                <p className="meta">
                  Elapsed {elapsedSeconds}s. Some platforms can take a minute or two, especially YouTube transcripts and Instagram captions.
                </p>
              </div>
              <div className="spinner" aria-label="Loading" />
            </div>
            <div className="steps">
              {loadingSteps.map((step, index) => (
                <div className={`step ${index < activeStep ? "done" : ""} ${index === activeStep ? "active" : ""}`} key={step}>
                  <span>{index + 1}</span>
                  <p>{step}</p>
                </div>
              ))}
            </div>
            <p className="meta">
              Keep this tab open. The backend returns partial JSON only when the current extraction request finishes.
            </p>
          </div>
        ) : null}

        <div className="panel stack">
          <div className="header">
            <div>
              <h2>Output</h2>
              <p className="meta">Each extracted link has its own transcript, caption, summary, and download actions.</p>
            </div>
            <div className="actions">
              <button
                onClick={() => downloadText("transcripts.csv", transcriptCsv(extractedItems), "text/csv;charset=utf-8")}
                disabled={extractedItems.length === 0}
              >
                Download CSV
              </button>
              <button onClick={summarizeExtractedContent} disabled={loading || summarizing || !selectedItem}>
                {summarizing ? "Summarizing..." : "Summarize Selected"}
              </button>
            </div>
          </div>

          <div className="resultTableWrap">
            <table className="resultTable">
              <thead>
                <tr>
                  <th>Platform</th>
                  <th>Title</th>
                  <th>Transcript</th>
                  <th>Caption</th>
                  <th>Summary</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {extractedItems.length > 0 ? extractedItems.map((item, index) => {
                  const isSelected = selectedItem?.key === item.key;
                  const videoHref = downloadVideoUrl(item.url);
                  return (
                    <tr className={isSelected ? "selectedRow" : ""} key={item.key}>
                      <td><span className={`badge ${item.platform}`}>{item.platform}</span></td>
                      <td>
                        <button className="textButton" onClick={() => setSelectedIndex(index)}>{item.label}</button>
                        {item.url ? <p className="meta">{item.url}</p> : null}
                      </td>
                      <td>{item.transcript ? "Ready" : item.transcriptStatus || "Missing"}</td>
                      <td>{item.caption ? "Ready" : "Missing"}</td>
                      <td>{summaries[item.key] ? "Ready" : "Not yet"}</td>
                      <td>
                        <div className="rowActions">
                          <button onClick={() => setSelectedIndex(index)}>View</button>
                          <button
                            onClick={() => downloadText(`${safeFilename(item.label, "transcript")}.txt`, item.transcript || "")}
                            disabled={!item.transcript}
                          >
                            TXT
                          </button>
                          {videoHref ? <a className="buttonLink" href={videoHref}>Video</a> : <button disabled>Video</button>}
                        </div>
                      </td>
                    </tr>
                  );
                }) : (
                  <tr>
                    <td colSpan={6} className="emptyCell">Extract links to populate the results table.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="outputGrid">
            <label className="stack">
              <span className="label">Video Transcript</span>
              <textarea
                readOnly
                rows={18}
                value={selectedItem?.transcript || ""}
                placeholder="Transcript output will appear here after extraction."
              />
            </label>

            <label className="stack">
              <span className="label">Caption</span>
              <textarea
                readOnly
                rows={18}
                value={selectedItem?.caption || ""}
                placeholder="Caption output will appear here after extraction."
              />
            </label>
          </div>

          <label className="stack">
            <span className="label">Summarisation</span>
            <textarea
              readOnly
              rows={14}
              value={selectedSummary}
              placeholder="Summary output will appear here after you click Summarize Transcript."
            />
          </label>
        </div>

        {backendJson ? (
          <div className="panel stack">
            <h2>Backend JSON</h2>
            <textarea readOnly rows={14} value={backendJson} />
          </div>
        ) : null}
      </section>
    </main>
  );
}
