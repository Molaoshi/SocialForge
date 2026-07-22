# SocialForge

AI-Powered Social Media Automation App powered by Grok 4.5 + Grok Imagine.

## Features
- Topic research + batch content generation
- Grok Imagine image generation
- Multi-platform posting (X, Instagram, Threads, LinkedIn, Facebook)
- Scheduling & queue system

## Current Data

### Rejection & Resilience Batch (50 posts)
Location: `data/rejection_posts.json`

Contains 50 ready-to-schedule posts with:
- Quote
- Full caption (with hashtags)
- Boldness level (mild / medium / high)
- Sci-fi cyberpunk image prompt
- Status + target platforms

Perfect for testing the scheduling pipeline.

## Quick Start

```bash
git clone https://github.com/Molaoshi/SocialForge.git
cd SocialForge
pip install -r requirements.txt
# Copy .env.example to .env and add your API keys
uvicorn main:app --reload
```

## Project Structure
```
SocialForge/
├── data/
│   └── rejection_posts.json   # 50 posts ready for scheduling
├── main.py                    # FastAPI backend
├── content_generator.py       # Content generation logic
├── imagine.py                 # Grok Imagine integration
├── models.py                  # SQLAlchemy models
└── .env.example
```

## Next Steps
- Load JSON into database
- Generate actual images from prompts
- Connect platform APIs
- Build simple scheduler UI
