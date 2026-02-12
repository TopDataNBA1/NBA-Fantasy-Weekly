"""
NBA Fantasy Salary Cup Edition — Daily Scraper v3
Fetches all entries from the NBA Fantasy API for league 431 (TOTAL)
and computes weekly rankings (Mon-Sun).

Key findings about the API:
  - All point values are multiplied by 10 (divide by 10 for real points)
  - total: cumulative season points (×10)
  - event_total: points scored TODAY (×10), not the whole week
  - phase=1 gives the overall season standings (what we want)
  - Weekly ranking = sum of daily event_totals across the week
    OR = (total on latest day) - (total at start of week)
"""

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- Configuration ---
LEAGUE_ID = 431
PHASE = 1  # phase=1 = overall season standings
API_BASE = "https://es.nbafantasy.nba.com/api/leagues-classic"
PER_PAGE = 50
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_DELAY = 0.5
POINTS_DIVISOR = 10  # API returns values ×10

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "data.json"


def fetch_standings_page(page):
    """Fetch a single page of standings."""
    url = (
        f"{API_BASE}/{LEAGUE_ID}/standings/"
        f"?page_new_entries=1&page_standings={page}&phase={PHASE}"
    )

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; NBAFantasyWeekly/1.0)",
                "Referer": "https://es.nbafantasy.nba.com/"
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES} failed for page {page}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise
        except Exception as e:
            print(f"  Unexpected error on page {page}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise


def fetch_all_standings():
    """Fetch all pages of standings."""
    all_entries = []
    page = 1
    total_pages_estimate = "?"

    print(f"Fetching standings for league {LEAGUE_ID}, phase {PHASE}...")

    while True:
        print(f"  Page {page}/{total_pages_estimate}...", end=" ", flush=True)

        data = fetch_standings_page(page)
        standings = data.get("standings", {})
        results = standings.get("results", [])
        has_next = standings.get("has_next", False)

        all_entries.extend(results)
        print(f"got {len(results)} entries (total: {len(all_entries)})")

        if not has_next or len(results) == 0:
            break

        page += 1
        if page == 2:
            total_pages_estimate = "~1200+"

        time.sleep(REQUEST_DELAY)

    last_updated = data.get("last_updated_data", "")
    return all_entries, last_updated


def get_today_str():
    """Get today's date in YYYY-MM-DD (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_week_bounds(date_str):
    """Get Monday and Sunday of the week containing the given date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def save_daily_snapshot(entries, date_str):
    """Save today's raw standings data."""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "date": date_str,
        "count": len(entries),
        "entries": [
            {
                "entry": e["entry"],
                "player_name": e["player_name"],
                "entry_name": e["entry_name"],
                "total": e["total"],
                "event_total": e["event_total"],
            }
            for e in entries
        ]
    }

    filepath = DAILY_DIR / f"{date_str}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)

    print(f"Saved daily snapshot: {filepath} ({len(entries)} entries)")
    return snapshot


def load_daily_snapshot(date_str):
    """Load a daily snapshot if it exists."""
    filepath = DAILY_DIR / f"{date_str}.json"
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def compute_weekly_ranking(today_str):
    """
    Compute weekly ranking based on daily snapshots.

    - event_total = today's points (×10)
    - Weekly total = sum of event_totals for each day we have data
      OR for days we missed, use total(day_after) - total(day_before)
    - Daily points column = event_total / 10 for each day
    - Movement = rank change vs yesterday
    """
    monday_str, sunday_str = get_week_bounds(today_str)
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")

    print(f"Computing weekly ranking for {monday_str} to {sunday_str}")

    # Load all available daily snapshots for this week
    daily_snapshots = {}
    for i in range(7):
        day_dt = monday_dt + timedelta(days=i)
        day_str = day_dt.strftime("%Y-%m-%d")
        if day_dt > today_dt:
            break
        snapshot = load_daily_snapshot(day_str)
        if snapshot:
            daily_snapshots[day_str] = snapshot
            print(f"  Loaded {day_str} ({snapshot['count']} entries)")

    if not daily_snapshots:
        print("No snapshots available for this week!")
        return None

    sorted_days = sorted(daily_snapshots.keys())
    latest_day = sorted_days[-1]

    # Build lookups
    # entry_id -> {day_str: {total, event_total}}
    entry_daily = {}
    entry_info = {}

    for day_str, snapshot in daily_snapshots.items():
        for e in snapshot["entries"]:
            eid = e["entry"]
            entry_info[eid] = {
                "player_name": e["player_name"],
                "entry_name": e["entry_name"],
            }
            if eid not in entry_daily:
                entry_daily[eid] = {}
            entry_daily[eid][day_str] = {
                "total": e["total"],
                "event_total": e["event_total"],
            }

    # Also try to load last Sunday (day before this week) for gap filling
    prev_sunday_str = (monday_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_sunday_snapshot = load_daily_snapshot(prev_sunday_str)
    prev_sunday_totals = {}
    if prev_sunday_snapshot:
        print(f"  Loaded previous week end: {prev_sunday_str}")
        for e in prev_sunday_snapshot["entries"]:
            prev_sunday_totals[e["entry"]] = e["total"]

    # Compute weekly data for each entry
    yesterday_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    weekly_data = []

    for eid, info in entry_info.items():
        daily = entry_daily.get(eid, {})

        # Build day-by-day points array (Mon=0 to Sun=6)
        days_array = [None] * 7
        weekly_total = 0

        for i in range(7):
            day_dt = monday_dt + timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")

            if day_str in daily:
                # We have a snapshot for this day
                day_pts = daily[day_str]["event_total"] // POINTS_DIVISOR
                days_array[i] = day_pts
                weekly_total += day_pts
            elif day_str <= today_str:
                # We missed this day — try to compute from surrounding totals
                # Find nearest previous and next snapshots
                prev_total = None
                next_total = None

                # Look backwards for previous total
                if i == 0 and eid in prev_sunday_totals:
                    prev_total = prev_sunday_totals[eid]
                else:
                    for j in range(i - 1, -1, -1):
                        prev_day = (monday_dt + timedelta(days=j)).strftime("%Y-%m-%d")
                        if prev_day in daily:
                            prev_total = daily[prev_day]["total"]
                            break
                    if prev_total is None and eid in prev_sunday_totals:
                        prev_total = prev_sunday_totals[eid]

                # Look forward
                for j in range(i + 1, 7):
                    next_day = (monday_dt + timedelta(days=j)).strftime("%Y-%m-%d")
                    if next_day in daily:
                        next_total = daily[next_day]["total"]
                        break

                # If we have both, we can estimate the gap but can't split per day
                # Leave as None (unknown) for now
                days_array[i] = None

        # If we only have today's snapshot and no previous reference,
        # try computing weekly total from total difference
        if len(sorted_days) == 1 and eid in prev_sunday_totals:
            today_total = daily[sorted_days[0]]["total"]
            week_diff = (today_total - prev_sunday_totals[eid]) // POINTS_DIVISOR
            # This gives Mon+Tue+...+today combined
            # We already have today's event_total, so the rest is the gap
            weekly_total = week_diff

        weekly_data.append({
            "entry": eid,
            "player_name": info["player_name"],
            "entry_name": info["entry_name"],
            "days": days_array,
            "total": weekly_total,
        })

    # Sort by weekly total descending
    weekly_data.sort(key=lambda x: x["total"], reverse=True)

    # Assign ranks
    for i, entry in enumerate(weekly_data):
        entry["rank"] = i + 1

    # Compute movement (today's rank vs yesterday's rank in weekly standings)
    if yesterday_str in daily_snapshots:
        # Build yesterday's weekly totals
        yesterday_weekly = {}
        for eid in entry_info:
            daily = entry_daily.get(eid, {})
            yday_total = 0
            for day_str in sorted_days:
                if day_str > yesterday_str:
                    break
                if day_str in daily:
                    yday_total += daily[day_str]["event_total"] // POINTS_DIVISOR
            yesterday_weekly[eid] = yday_total

        sorted_yesterday = sorted(yesterday_weekly.items(), key=lambda x: x[1], reverse=True)
        yesterday_rank_map = {eid: rank + 1 for rank, (eid, _) in enumerate(sorted_yesterday)}

        for entry in weekly_data:
            eid = entry["entry"]
            if eid in yesterday_rank_map:
                entry["movement"] = yesterday_rank_map[eid] - entry["rank"]
            else:
                entry["movement"] = 0
    else:
        for entry in weekly_data:
            entry["movement"] = 0

    return weekly_data


def build_output(weekly_data, today_str, last_updated):
    """Build the final JSON output for the frontend."""
    monday_str, sunday_str = get_week_bounds(today_str)
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")

    today_index = today_dt.weekday()

    day_labels = []
    for i in range(7):
        day_dt = monday_dt + timedelta(days=i)
        day_labels.append(day_dt.strftime("%a"))

    output = {
        "meta": {
            "week_start": monday_str,
            "week_end": sunday_str,
            "today": today_str,
            "today_index": today_index,
            "day_labels": day_labels,
            "total_players": len(weekly_data),
            "last_updated": last_updated,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "rankings": [
            {
                "r": e["rank"],
                "p": e["player_name"],
                "t": e["entry_name"],
                "d": e["days"],
                "w": e["total"],
                "m": e.get("movement", 0),
            }
            for e in weekly_data
        ]
    }

    return output


def main():
    print("=" * 60)
    print("NBA Fantasy Salary Cup — Daily Scraper v3")
    print("=" * 60)

    today_str = get_today_str()
    print(f"Date: {today_str}")

    # Fetch all standings
    start_time = time.time()
    entries, last_updated = fetch_all_standings()
    elapsed = time.time() - start_time
    print(f"\nFetched {len(entries)} entries in {elapsed:.1f}s")

    if not entries:
        print("ERROR: No entries fetched. Aborting.")
        return

    # Quick sanity check
    top = entries[0]
    print(f"Top entry: {top['player_name']} ({top['entry_name']})")
    print(f"  total={top['total']} ({top['total']//POINTS_DIVISOR} real)")
    print(f"  event_total={top['event_total']} ({top['event_total']//POINTS_DIVISOR} real)")

    # Save daily snapshot
    save_daily_snapshot(entries, today_str)

    # Compute weekly ranking
    weekly_data = compute_weekly_ranking(today_str)

    if weekly_data:
        output = build_output(weekly_data, today_str, last_updated)

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False)

        print(f"\nOutput saved: {OUTPUT_FILE}")
        print(f"Total players in ranking: {len(weekly_data)}")
        print(f"Top 5 weekly:")
        for e in weekly_data[:5]:
            days_str = [str(d) if d is not None else "-" for d in e["days"]]
            print(f"  #{e['rank']} {e['player_name']} ({e['entry_name']}) — "
                  f"Week: {e['total']} pts — Days: [{', '.join(days_str)}]")
    else:
        print("Could not compute weekly ranking.")

    print("\nDone!")


if __name__ == "__main__":
    main()
