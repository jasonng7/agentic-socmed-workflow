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
INSTAGRAM_USERNAME=your_instagram_username
INSTAGRAM_SESSION_FILE=/home/ubuntu/instagram-session
```

YouTube cookies should be a Netscape-format `cookies.txt` exported from a browser session. Instagram session files can be created with Instaloader on your local machine or EC2, then referenced by path.

Endpoints:

- `GET /health`
- `POST /route`
- `POST /extract`
- `POST /summarize`

The backend uses temporary directories for extraction work and returns JSON instead of persistent output files by default.
