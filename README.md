# Agentic Socmed Workflow

A standalone Streamlit workflow that accepts free-form text containing one or more social media URLs, routes each URL to the correct platform scraper, asks for the extraction options needed by those workflows, and saves a combined `.txt` run summary.

Supported platforms:

- Instagram
- YouTube
- RedNote / Xiaohongshu

## Run

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

Optional LLM configuration can be placed in `.env`:

```bash
OPENAI_API_KEY=your_openai_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

OpenRouter-compatible variables are also supported as a fallback.

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
