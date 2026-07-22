# SocialForge

AI-Powered Social Media Automation App powered by **Grok 4.5** + **Grok Imagine**.

## Features
- Topic research + batch content generation
- Grok Imagine image generation
- Multi-platform posting (X, Instagram, Threads, LinkedIn, Facebook)
- Scheduling & queue system (APScheduler)
- FastAPI backend with clean endpoints

## Current Data

### Rejection & Resilience Batch (50 posts)
Location: `data/rejection_posts.json`

Contains 50 ready-to-schedule posts with:
- Quote
- Full caption (with hashtags)
- Boldness level (`mild` / `medium` / `high`)
- Sci-fi cyberpunk image prompt
- Status + target platforms

## Quick Start

```bash
git clone https://github.com/Molaoshi/SocialForge.git
cd SocialForge
pip install -r requirements.txt

# Seed the 50 posts into SQLite
python seed_db.py

# Start the API
uvicorn main:app --reload
```

Open http://localhost:8000/docs for interactive API docs.

## Useful Endpoints

| Method | Endpoint                  | Description                          |
|--------|---------------------------|--------------------------------------|
| GET    | `/`                       | Health + available routes            |
| GET    | `/posts`                  | List posts (filter by status/boldness) |
| GET    | `/posts/{id}`             | Get single post                      |
| GET    | `/posts/batch/rejection`  | Raw JSON batch                       |
| POST   | `/posts/seed`             | Load JSON into database              |
| PATCH  | `/posts/{id}/status`      | Update status (draft → scheduled → posted) |
| GET    | `/health`                 | Simple health check                  |

## Project Structure

```
SocialForge/
├── data/
│   └── rejection_posts.json   # 50 posts ready for scheduling
├── main.py                    # FastAPI backend + endpoints
├── models.py                  # SQLAlchemy models (Post)
├── seed_db.py                 # One-time seeder for the JSON batch
├── content_generator.py       # Load / generate content
├── imagine.py                 # Grok Imagine stub
├── scheduler.py               # APScheduler background jobs
├── requirements.txt
└── .env.example
```

## Next Steps
1. Add real Grok Imagine API calls (xAI key)
2. Connect platform APIs (X, Meta, LinkedIn)
3. Build simple web UI or keep using the API
4. Deploy to Vercel / Railway / Render

Built for high-volume content creation + rejection resilience training.
