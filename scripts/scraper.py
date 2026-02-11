"""
NBA Fantasy Salary Cup Edition — Daily Scraper
Fetches all entries from the NBA Fantasy API for league 431 (TOTAL)
and computes weekly rankings (Mon-Sun).
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- Configuration ---
LEAGUE_ID = 431
API_BASE = "https://es.nbafantasy.nba.com/api/leagues-classic"
PER_PAGE = 50
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
REQUEST_DELAY = 0.5  # delay between requests to be respectful

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "data.json"


def get_current_phase():
    """Fetch the current phase/gameweek from a known entry."""
    url = "https://es.nbafantasy.nba.com/api/entry/8857/phase/1/standings/"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NBAFantasyWeekly/1.0)"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            # Find the entry for league 431 and get the latest phase
            for entry in data:
                if entry.get("league_id") == LEAGUE_ID:
                    return entry.get("phase", 1)
    except Exception as e:
        print(f"Warning: Could not detect phase automatically: {e}")

    # Fallback: try to detect from standings
    return None


def fetch_standings_page(page, phase):
    """Fetch a single page of standings."""
    url = (
        f"{API_BASE}/{LEAGUE_ID}/standings/"
        f"?page_new_entries=1&page_standings={page}&phase={phase}"
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


def fetch_all_standings(phase):
    """Fetch all pages of standings for a given phase."""
    all_entries = []
    page = 1
    total_pages_estimate = "?"

    print(f"Fetching standings for phase {phase}...")

    while True:
        print(f"  Page {page}/{total_pages_estimate}...", end=" ", flush=True)

        data = fetch_standings_page(page, phase)
        standings = data.get("standings", {})
        results = standings.get("results", [])
        has_next = standings.get("has_next", False)

        all_entries.extend(results)
        print(f"got {len(results)} entries (total: {len(all_entries)})")

        if not has_next or len(results) == 0:
            break

        page += 1
        # Estimate total pages
        if page == 2 and len(all_entries) > 0:
            league_info = data.get("league", {})
            total_pages_estimate = "~1200+"

        time.sleep(REQUEST_DELAY)

    return all_entries, data.get("last_updated_data", "")


def get_today_str():
    """Get today's date string in YYYY-MM-DD format (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_week_bounds(date_str):
    """
    Get Monday and Sunday of the week containing the given date.
    Returns (monday_str, sunday_str).
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())  # Monday
    sunday = monday + timedelta(days=6)  # Sunday
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def get_week_number(date_str):
    """Get ISO week number."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.isocalendar()[1]


def save_daily_snapshot(entries, phase, date_str):
    """Save today's raw standings data."""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "date": date_str,
        "phase": phase,
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
    Compute weekly ranking based on available daily snapshots.
    Week = Monday to Sunday.
    """
    monday_str, sunday_str = get_week_bounds(today_str)
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")

    print(f"Computing weekly ranking for week {monday_str} to {sunday_str}")

    # Load all available daily snapshots for this week
    daily_snapshots = {}
    for i in range(7):
        day_dt = monday_dt + timedelta(days=i)
        day_str = day_dt.strftime("%Y-%m-%d")
        snapshot = load_daily_snapshot(day_str)
        if snapshot:
            daily_snapshots[day_str] = snapshot
            print(f"  Loaded snapshot for {day_str} ({snapshot['count']} entries)")

    if not daily_snapshots:
        print("No snapshots available for this week!")
        return None

    # Get the latest snapshot to use as the base player list
    latest_day = max(daily_snapshots.keys())
    latest_snapshot = daily_snapshots[latest_day]

    # Build a lookup: entry_id -> {day_str: total_points}
    entry_totals = {}  # entry_id -> {date: total}
    entry_info = {}  # entry_id -> {player_name, entry_name}

    for day_str, snapshot in sorted(daily_snapshots.items()):
        for e in snapshot["entries"]:
            eid = e["entry"]
            entry_info[eid] = {
                "player_name": e["player_name"],
                "entry_name": e["entry_name"],
            }
            if eid not in entry_totals:
                entry_totals[eid] = {}
            entry_totals[eid][day_str] = e["total"]

    # We need a reference point: the total at the END of the day before Monday
    # (i.e., the Sunday of the previous week). If we don't have that,
    # we use the earliest available snapshot's total minus that day's event_total.
    # OR we use the first day of the week as baseline.

    # Strategy: Find the earliest day's data and compute daily deltas
    sorted_days = sorted(daily_snapshots.keys())

    # For the "previous day" reference (for movement calculation),
    # we need yesterday's ranking
    yesterday_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    # Compute weekly points for each entry
    weekly_data = []

    for eid, info in entry_info.items():
        totals = entry_totals.get(eid, {})

        # Calculate daily points (delta from previous day)
        day_points = {}
        prev_total = None

        for i in range(7):
            day_dt = monday_dt + timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")

            if day_str in totals:
                current_total = totals[day_str]
                if prev_total is not None:
                    day_points[day_str] = current_total - prev_total
                else:
                    # First day we have data — use event_total from snapshot
                    snapshot = daily_snapshots.get(day_str)
                    if snapshot:
                        for se in snapshot["entries"]:
                            if se["entry"] == eid:
                                day_points[day_str] = se["event_total"]
                                break
                    if day_str not in day_points:
                        day_points[day_str] = 0
                prev_total = current_total

        # Weekly total = sum of daily points
        weekly_total = sum(day_points.values())

        # Build day-by-day array (Mon=0 to Sun=6)
        days_array = []
        for i in range(7):
            day_dt = monday_dt + timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")
            if day_str in day_points:
                days_array.append(day_points[day_str])
            else:
                days_array.append(None)

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

    # Compute movement (change vs yesterday's ranking)
    # Yesterday's ranking = same computation but only with data up to yesterday
    yesterday_ranking = {}
    if yesterday_str in daily_snapshots and yesterday_str >= monday_str:
        # Rebuild yesterday's weekly totals
        for eid, info in entry_info.items():
            totals = entry_totals.get(eid, {})
            prev_total = None
            yday_total = 0

            for i in range(7):
                day_dt = monday_dt + timedelta(days=i)
                day_str = day_dt.strftime("%Y-%m-%d")
                if day_str > yesterday_str:
                    break
                if day_str in totals:
                    current_total = totals[day_str]
                    if prev_total is not None:
                        yday_total += current_total - prev_total
                    else:
                        snapshot = daily_snapshots.get(day_str)
                        if snapshot:
                            for se in snapshot["entries"]:
                                if se["entry"] == eid:
                                    yday_total += se["event_total"]
                                    break
                    prev_total = current_total

            yesterday_ranking[eid] = yday_total

        # Sort yesterday's data to get ranks
        sorted_yesterday = sorted(yesterday_ranking.items(), key=lambda x: x[1], reverse=True)
        yesterday_rank_map = {eid: rank + 1 for rank, (eid, _) in enumerate(sorted_yesterday)}

        # Apply movement
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


def build_output(weekly_data, phase, today_str, last_updated):
    """Build the final JSON output for the frontend."""
    monday_str, sunday_str = get_week_bounds(today_str)
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")

    # Determine which day index is "today" (0=Mon, 6=Sun)
    today_index = today_dt.weekday()

    # Day labels
    day_labels = []
    for i in range(7):
        day_dt = monday_dt + timedelta(days=i)
        day_labels.append(day_dt.strftime("%a"))

    output = {
        "meta": {
            "phase": phase,
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
    print("NBA Fantasy Salary Cup — Daily Scraper")
    print("=" * 60)

    today_str = get_today_str()
    print(f"Date: {today_str}")

    # Detect current phase
    phase = get_current_phase()
    if phase is None:
        # Try to read from last snapshot
        existing = sorted(DAILY_DIR.glob("*.json")) if DAILY_DIR.exists() else []
        if existing:
            with open(existing[-1]) as f:
                phase = json.load(f).get("phase", 18)
        else:
            phase = 18
    print(f"Phase: {phase}")

    # Fetch all standings
    start_time = time.time()
    entries, last_updated = fetch_all_standings(phase)
    elapsed = time.time() - start_time
    print(f"\nFetched {len(entries)} entries in {elapsed:.1f}s")

    if not entries:
        print("ERROR: No entries fetched. Aborting.")
        return

    # Save daily snapshot
    save_daily_snapshot(entries, phase, today_str)

    # Compute weekly ranking
    weekly_data = compute_weekly_ranking(today_str)

    if weekly_data:
        # Build and save output
        output = build_output(weekly_data, phase, today_str, last_updated)

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False)

        print(f"\nOutput saved: {OUTPUT_FILE}")
        print(f"Total players in ranking: {len(weekly_data)}")
        print(f"Top 5:")
        for e in weekly_data[:5]:
            print(f"  #{e['rank']} {e['player_name']} ({e['entry_name']}) — {e['total']} pts")
    else:
        print("Could not compute weekly ranking.")

    print("\nDone!")


if __name__ == "__main__":
    main()
