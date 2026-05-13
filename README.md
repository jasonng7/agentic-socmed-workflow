# Agentic Socmed Workflow

A social media workflow with two surfaces:

- A Vercel-ready Next.js frontend for lightweight URL routing, JSON-first review, and LLM summaries.
- A Streamlit/Python workflow for heavier local scraping, transcription, and media processing.

Supported platforms:

- Instagram
- YouTube
- RedNote / Xiaohongshu

## Run

### Vercel / Next.js UI

```bash
npm install
npm run dev
```

Set these environment variables in Vercel:

```bash
OPENAI_API_KEY=your_openai_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
NEXT_PUBLIC_BACKEND_URL=http://13.214.251.94:8000
```

When `NEXT_PUBLIC_BACKEND_URL` is configured, the Vercel UI calls the FastAPI backend `/extract` endpoint. Extraction returns transcripts, captions, metadata, and raw JSON first. The LLM only summarizes after you click **Summarize**, using the request typed in the focus box.

### FastAPI Backend

See [backend/README.md](backend/README.md) for EC2 deployment notes. The backend returns JSON, uses temporary directories for extraction work, and avoids persistent output files by default.

### Streamlit / Python Workflow

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Optional system dependency for temporary audio extraction before OpenAI transcription:

```bash
brew install ffmpeg
```

On Streamlit Community Cloud, `ffmpeg` is installed from `packages.txt`.

Optional LLM configuration can be placed in `.env`:

```bash
OPENAI_API_KEY=your_openai_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

OpenRouter-compatible variables are also supported as a fallback.

For Streamlit Community Cloud, add the same values in the app's **Advanced settings -> Secrets** field:

```toml
OPENAI_API_KEY = "your_openai_key_here"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = "gpt-4o-mini"
```

## Workflow

1. Paste any text containing links.
2. The router extracts URLs and identifies Instagram, YouTube, RedNote/Xiaohongshu, or unsupported links.
3. The interface shows the relevant options for each detected platform.
4. The platform workflows run concurrently up to the selected worker cap.
5. Captions and transcripts are selected by default where the platform supports them.
6. Extracted data is saved under `./outputs/{platform}`.
7. Review the raw transcript/caption content, then run an LLM summary only when needed.

## LLM Summary

When you click **Summarize**, the LLM uses video transcripts and captions as the primary source and follows the request typed in the focus box. There is no fixed backend summary template for the frontend summarize action.

## Notes

- The original `Unified Socmed Scraper` folder is not imported or modified.
- Normal platform URLs are routed directly. Short-link style URLs can be expanded when redirect resolution is enabled.
- Publicly available data is the intended scope.
