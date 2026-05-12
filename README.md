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
```

This Vercel UI is intentionally lightweight. It detects platforms, accepts extracted JSON/text, sends transcript/caption data to the LLM, and lets users download the summary as a `.txt` file. Heavy scraping, `ffmpeg`, video download, and Whisper should run in the Python workflow or a future FastAPI backend.

### Streamlit / Python Workflow

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Optional system dependency for video/audio transcription:

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
7. A raw run report and LLM content summary are saved under `./outputs/agentic_reports`.

## LLM Summary

When enabled, the LLM summary uses video transcripts and captions as the primary source. It detects the likely content category and extracts useful details:

- Travel content: places, landmarks, cities, countries, activities, hotels, routes, and practical notes mentioned.
- Food content: dishes, restaurant or stall names, food locations, prices, ordering tips, and recommendation signals mentioned.
- Other content: main topic, important entities, claims, instructions, calls to action, and missing details.

## Notes

- The original `Unified Socmed Scraper` folder is not imported or modified.
- Normal platform URLs are routed directly. Short-link style URLs can be expanded when redirect resolution is enabled.
- Publicly available data is the intended scope.
