# 🏀 NBA Fantasy — Salary Cup Edition — Weekly Ranking

Automated weekly ranking for the NBA Fantasy Salary Cup league (60,000+ players).  
The official site doesn't provide weekly standings — this project fills that gap.

## How it works

1. **GitHub Actions** runs a Python scraper daily at **8:00 AM CEST**
2. The scraper fetches all ~60,000 entries from the NBA Fantasy API (~1,200 pages)
3. It computes the **weekly ranking** (Monday to Sunday) with daily point breakdowns
4. Results are saved as a JSON file and served via **GitHub Pages**

## Setup

### 1. Create the repository

Create a new GitHub repository and push this code:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/nba-fantasy-weekly.git
git push -u origin main
```

### 2. Enable GitHub Pages

1. Go to your repo → **Settings** → **Pages**
2. Under "Source", select **Deploy from a branch**
3. Branch: `main`, folder: `/docs`
4. Click **Save**

Your site will be available at: `https://YOUR_USERNAME.github.io/nba-fantasy-weekly/`

### 3. Run the scraper for the first time

1. Go to **Actions** tab in your repo
2. Click on **"Daily NBA Fantasy Scraper"** in the left sidebar
3. Click **"Run workflow"** → **"Run workflow"**
4. Wait ~20 minutes for it to complete

The scraper will now run automatically every day at 8:00 AM CEST.

### 4. (Optional) Run locally

```bash
python scripts/scraper.py
```

This will create files in `data/daily/` and `docs/data.json`.

## Project structure

```
nba-fantasy-weekly/
├── .github/workflows/
│   └── scrape.yml          # GitHub Actions daily cron job
├── scripts/
│   └── scraper.py          # Python scraper (no dependencies needed)
├── data/
│   └── daily/              # Daily snapshots (auto-generated)
│       ├── 2026-02-10.json
│       └── 2026-02-11.json
├── docs/
│   ├── index.html          # Frontend (served by GitHub Pages)
│   └── data.json           # Rankings data (auto-generated)
└── README.md
```

## Key details

- **No external Python dependencies** — uses only stdlib (`urllib`, `json`, `time`)
- **No authentication needed** — the NBA Fantasy API is public
- **~20 min per scrape** — well within GitHub Actions free tier (2,000 min/month)
- **Weekly ranking** = sum of daily point differences (Monday to Sunday)
- **Movement** = rank change vs previous day's weekly ranking

## Customization

- **Change scrape time**: Edit the cron in `.github/workflows/scrape.yml`
- **Change league**: Edit `LEAGUE_ID` in `scripts/scraper.py`
- **Adjust request speed**: Edit `REQUEST_DELAY` in `scripts/scraper.py`

## Notes

- The first day of the week only has `event_total` (daily points from the API)
- From day 2 onwards, daily points are calculated as the difference in `total`
- Daily snapshots are kept in `data/daily/` for historical reference
- The scraper is respectful: 0.5s delay between requests, proper User-Agent
