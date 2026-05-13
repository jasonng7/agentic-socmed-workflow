# Agentic Socmed Workflow Backend

FastAPI backend for the Vercel frontend. It runs the Python scrapers and returns JSON-first extraction results.

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## EC2 Notes

Install system packages:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg
```

Environment variables:

```bash
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
ALLOWED_ORIGINS=https://your-vercel-app.vercel.app
```

Optional but recommended when platforms block anonymous scraping:

```bash
YOUTUBE_COOKIES_FILE=/home/ubuntu/youtube-cookies.txt
YOUTUBE_BROWSER=chrome
INSTAGRAM_USERNAME=your_instagram_username
INSTAGRAM_SESSION_FILE=/home/ubuntu/instagram-session
```

YouTube cookies should be a Netscape-format `cookies.txt` exported from a browser session. If `YOUTUBE_COOKIES_FILE` is not set, `YOUTUBE_BROWSER` is passed to `yt-dlp --cookies-from-browser`, which is useful on a local machine with browser profiles but is usually not suitable for headless EC2. Instagram session files can be created with Instaloader on your local machine or EC2, then referenced by path.

Polite delay settings:

```bash
SCRAPER_MIN_DELAY_SECONDS=2
SCRAPER_MAX_DELAY_SECONDS=6
```

The backend adds a random delay in that range before platform calls. EC2/data-center IPs are often treated more strictly than residential laptop IPs, so keeping requests slow and non-bursty helps reduce platform blocks. It does not guarantee access if the platform requires cookies or a logged-in session.

Whisper fallback:

```bash
BACKEND_USE_WHISPER=true
OPENAI_WHISPER_MODEL=whisper-1
```

This downloads audio temporarily when captions/transcripts are unavailable, transcribes it with OpenAI's hosted Audio Transcriptions API, and deletes temporary media after the request. It removes the need to host `mlx-whisper` or `openai-whisper` on EC2.

Endpoints:

- `GET /health`
- `POST /route`
- `POST /extract`
- `POST /summarize`

The backend uses temporary directories for extraction work and returns JSON instead of persistent output files by default.
