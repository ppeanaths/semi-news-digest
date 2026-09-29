# Semiconductor News Digest

Fetches news for a semiconductor watchlist, summarizes it with Claude, and posts a daily digest to Discord.

## Setup
1. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your keys
4. Edit `config/watchlist.yaml`
5. `python src/main.py`

## Disclaimer
For information only. Not investment advice.
