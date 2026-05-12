"use client";

import { useEffect, useMemo, useState } from "react";
import { routeInput, RoutedUrl } from "@/lib/router";

const sampleInput = `http://xhslink.com/o/3ve11ncSu5h
https://www.youtube.com/shorts/ys_3Q025Pu0
https://www.instagram.com/p/DVbOZ0EkyUp/`;

type AnalyzeResponse = {
  summary?: string;
  results?: unknown;
  error?: string;
  details?: unknown;
};

export default function Home() {
  const [input, setInput] = useState(sampleInput);
  const [preference, setPreference] = useState("Summarize what the content is about. If travel, list places mentioned. If food, list food locations and venue details.");
  const [extractionText, setExtractionText] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [summary, setSummary] = useState("");
  const [backendJson, setBackendJson] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  const routes = useMemo(() => routeInput(input), [input]);
  const supported = routes.filter((route) => route.platform !== "unsupported");
  const unsupported = routes.filter((route) => route.platform === "unsupported");
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "");
  const loadingSteps = useMemo(
    () => [
      "Routing links by platform",
      backendUrl ? "Calling EC2 extraction backend" : "Preparing local LLM summary request",
      "Extracting captions, transcripts, and metadata",
      "Generating LLM content summary",
      "Returning JSON results"
    ],
    [backendUrl]
  );
  const activeStep = loading ? Math.min(Math.floor(elapsedSeconds / 12), loadingSteps.length - 1) : -1;

  useEffect(() => {
    if (!loading || !startedAt) {
      return;
    }
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [loading, startedAt]);

  async function analyze() {
    setLoading(true);
    setStartedAt(Date.now());
    setElapsedSeconds(0);
    setError("");
    setSummary("");
    setBackendJson("");

    let extractionJson: unknown = undefined;
    if (jsonText.trim()) {
      try {
        extractionJson = JSON.parse(jsonText);
      } catch {
        setError("Extraction JSON is not valid JSON.");
        setLoading(false);
        setStartedAt(null);
        return;
      }
    }

    const endpoint = backendUrl ? `${backendUrl}/extract` : "/api/analyze";
    const body = backendUrl
      ? {
          input,
          user_preference: preference,
          summarize: true,
          resolve_redirects: true,
          include_instagram_caption: true,
          include_instagram_transcript: false,
          include_youtube_metadata: true,
          include_youtube_transcript: true,
          include_xhs_caption: true,
          max_videos_per_collection: 5,
          use_whisper: false
        }
      : {
          input,
          userPreference: preference,
          extractionText,
          extractionJson
        };

    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
    } catch {
      setError("Could not reach the backend. Check that EC2 is running and NEXT_PUBLIC_BACKEND_URL is correct.");
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

    setSummary(data.summary || "No summary returned.");
    setBackendJson(data.results ? JSON.stringify(data.results, null, 2) : "");
    setLoading(false);
    setStartedAt(null);
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
            JSON-first interface for routing links, calling the Python backend, and summarizing transcript/caption data.
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
            Set NEXT_PUBLIC_BACKEND_URL in Vercel to call your EC2 FastAPI backend. Without it, this page runs in LLM-summary-only mode.
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
              placeholder='Fallback mode only: [{"platform":"youtube","caption":"...","transcript":"..."}]'
            />
          </label>

          <label className="stack">
            <span className="label">Optional transcript/caption text</span>
            <textarea
              rows={12}
              value={extractionText}
              onChange={(event) => setExtractionText(event.target.value)}
              placeholder="Fallback mode only: paste transcript and caption text here."
            />
          </label>
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

        {summary ? (
          <div className="panel stack">
            <div className="header">
              <h2>LLM Content Summary</h2>
              <button onClick={downloadSummary}>Download TXT</button>
            </div>
            <div className="summary">{summary}</div>
          </div>
        ) : null}

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
