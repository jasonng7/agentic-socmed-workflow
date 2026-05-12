"use client";

import { useMemo, useState } from "react";
import { routeInput, RoutedUrl } from "@/lib/router";

const sampleInput = `http://xhslink.com/o/3ve11ncSu5h
https://www.youtube.com/shorts/ys_3Q025Pu0
https://www.instagram.com/p/DVbOZ0EkyUp/`;

type AnalyzeResponse = {
  summary?: string;
  error?: string;
  details?: unknown;
};

export default function Home() {
  const [input, setInput] = useState(sampleInput);
  const [preference, setPreference] = useState("Summarize what the content is about. If travel, list places mentioned. If food, list food locations and venue details.");
  const [extractionText, setExtractionText] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const routes = useMemo(() => routeInput(input), [input]);
  const supported = routes.filter((route) => route.platform !== "unsupported");
  const unsupported = routes.filter((route) => route.platform === "unsupported");

  async function analyze() {
    setLoading(true);
    setError("");
    setSummary("");

    let extractionJson: unknown = undefined;
    if (jsonText.trim()) {
      try {
        extractionJson = JSON.parse(jsonText);
      } catch {
        setError("Extraction JSON is not valid JSON.");
        setLoading(false);
        return;
      }
    }

    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input,
        userPreference: preference,
        extractionText,
        extractionJson
      })
    });

    const data = (await response.json()) as AnalyzeResponse;
    if (!response.ok || data.error) {
      setError(data.error || "Analysis failed.");
      setLoading(false);
      return;
    }

    setSummary(data.summary || "No summary returned.");
    setLoading(false);
  }

  function downloadSummary() {
    const blob = new Blob([summary], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `llm-content-summary-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.txt`;
    link.click();
    URL.revokeObjectURL(url);
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

  return (
    <main className="shell">
      <aside className="sidebar stack">
        <div className="stack">
          <p className="kicker">Vercel Frontend</p>
          <h1>Agentic Socmed Workflow</h1>
          <p className="meta">
            Lightweight JSON-first interface for routing links and summarizing extracted transcript/caption data.
          </p>
        </div>

        <div className="panel stack">
          <h2>Default Extraction</h2>
          <div className="checks">
            <label className="check">
              <input checked readOnly type="checkbox" />
              Caption
            </label>
            <label className="check">
              <input checked readOnly type="checkbox" />
              Transcript
            </label>
            <label className="check">
              <input checked readOnly type="checkbox" />
              Metadata
            </label>
            <label className="check">
              <input readOnly type="checkbox" />
              Video download only as temporary backend step
            </label>
          </div>
        </div>

        <div className="panel stack">
          <h2>Backend Note</h2>
          <p className="meta">
            This Vercel app does not run heavy scraping, ffmpeg, or Whisper. Paste extracted JSON/text here now; later this UI can call a FastAPI backend.
          </p>
        </div>
      </aside>

      <section className="main stack">
        <div className="header">
          <div className="stack">
            <p className="kicker">Step 1</p>
            <h1>Paste Links</h1>
          </div>
          <button onClick={analyze} disabled={loading}>
            {loading ? "Analyzing..." : "Generate Summary"}
          </button>
        </div>

        <div className="grid">
          <label className="stack">
            <span className="label">Input links or text containing links</span>
            <textarea rows={8} value={input} onChange={(event) => setInput(event.target.value)} />
          </label>

          <label className="stack">
            <span className="label">What should the LLM focus on?</span>
            <textarea rows={8} value={preference} onChange={(event) => setPreference(event.target.value)} />
          </label>
        </div>

        <div className="panel stack">
          <h2>Detected Routes</h2>
          {routes.length === 0 ? <p className="meta">No URLs detected yet.</p> : <div className="grid">{routes.map(routeCard)}</div>}
          {unsupported.length > 0 ? <p className="error">{unsupported.length} unsupported URL(s) detected.</p> : null}
          {supported.length > 0 ? <p className="meta">{supported.length} supported URL(s) ready for the backend workflow.</p> : null}
        </div>

        <div className="grid">
          <label className="stack">
            <span className="label">Optional extracted JSON</span>
            <textarea
              rows={12}
              value={jsonText}
              onChange={(event) => setJsonText(event.target.value)}
              placeholder='[{"platform":"youtube","caption":"...","transcript":"..."}]'
            />
          </label>

          <label className="stack">
            <span className="label">Optional transcript/caption text</span>
            <textarea
              rows={12}
              value={extractionText}
              onChange={(event) => setExtractionText(event.target.value)}
              placeholder="Paste transcript and caption text here while the backend integration is being prepared."
            />
          </label>
        </div>

        {error ? <div className="panel error">{error}</div> : null}

        {summary ? (
          <div className="panel stack">
            <div className="header">
              <h2>LLM Content Summary</h2>
              <button onClick={downloadSummary}>Download TXT</button>
            </div>
            <div className="summary">{summary}</div>
          </div>
        ) : null}
      </section>
    </main>
  );
}
