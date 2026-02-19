"""
NBA Fantasy Salary Cup Edition — Daily Scraper v4
Fetches all entries from the NBA Fantasy API for league 431 (TOTAL)
and computes weekly rankings (Mon-Sun).

Key design:
  - Uses /api/events/ to know EXACTLY which days have games
  - Uses delta of 'total' between consecutive snapshots for daily points
  - Days without scheduled events show as null (—)
  - No reliance on event_total (which can bleed across days)
  - All API point values are ×10, we divide by 10 for display
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
API_BASE = "https://es.nbafantasy.nba.com/api"
PER_PAGE = 50
MAX_RETRIES = 3
RETRY_DELAY = 5
REQUEST_DELAY = 0.5
POINTS_DIVISOR = 10  # API returns values ×10

# Season start: Week 1 began Monday Oct 20, 2025
SEASON_START = datetime(2025, 10, 20)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
EVENTS_FILE = DATA_DIR / "events.json"
OUTPUT_FILE = PROJECT_ROOT / "docs" / "data.json"


def fetch_json(url):
    """Fetch JSON from a URL with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; NBAFantasyWeekly/1.0)",
                "Referer": "https://es.nbafantasy.nba.com/"
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"  Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise


def fetch_events():
    """Fetch the full events calendar."""
    print("Fetching events calendar...")
    url = f"{API_BASE}/events/"
    events = fetch_json(url)
    print(f"  Got {len(events)} events")
    return events


def get_game_dates_for_week(events, monday_str, sunday_str):
    """
    Given the events list, return a dict mapping day-of-week index (0=Mon..6=Sun)
    to the event(s) on that day.
    
    The deadline_time is in UTC and represents when games start.
    We convert to US Eastern to get the actual game date.
    """
    ET = timezone(timedelta(hours=-5))  # EST
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")
    
    game_days = {}  # day_index -> list of event ids
    
    for event in events:
        if not event.get("deadline_time"):
            continue
        
        # Parse deadline_time and convert to ET to get the game date
        dt_utc = datetime.fromisoformat(event["deadline_time"].replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ET)
        game_date_str = dt_et.strftime("%Y-%m-%d")
        game_date = datetime.strptime(game_date_str, "%Y-%m-%d")
        
        # Check if this event falls within our week
        if monday_str <= game_date_str <= sunday_str:
            day_index = (game_date - monday_dt).days
            if 0 <= day_index <= 6:
                if day_index not in game_days:
                    game_days[day_index] = []
                game_days[day_index].append(event["id"])
    
    return game_days


def get_jornada_number(events, monday_str, sunday_str):
    """Extract the Jornada number from events in this week."""
    ET = timezone(timedelta(hours=-5))
    
    for event in events:
        if not event.get("deadline_time") or not event.get("name"):
            continue
        dt_utc = datetime.fromisoformat(event["deadline_time"].replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ET)
        game_date_str = dt_et.strftime("%Y-%m-%d")
        
        if monday_str <= game_date_str <= sunday_str:
            # Extract number from "Jornada 18 - Día 1"
            name = event["name"]
            if "Jornada" in name:
                try:
                    return int(name.split("Jornada")[1].split("-")[0].strip())
                except (ValueError, IndexError):
                    pass
    return None


def fetch_standings_page(page):
    """Fetch a single page of standings."""
    url = (
        f"{API_BASE}/leagues-classic/{LEAGUE_ID}/standings/"
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


def fetch_all_standings():
    """Fetch all pages of standings."""
    all_entries = []
    page = 1

    print(f"Fetching standings for league {LEAGUE_ID}, phase {PHASE}...")

    while True:
        print(f"  Page {page}...", end=" ", flush=True)

        data = fetch_standings_page(page)
        standings = data.get("standings", {})
        results = standings.get("results", [])
        has_next = standings.get("has_next", False)

        all_entries.extend(results)
        print(f"got {len(results)} (total: {len(all_entries)})")

        if not has_next or len(results) == 0:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    last_updated = data.get("last_updated_data", "")
    return all_entries, last_updated


def get_game_date_str():
    """
    Get the game date that today's scraper run corresponds to.
    The scraper runs at 8:00 AM CEST = 2:00 AM ET.
    At that point, data reflects YESTERDAY's games (ET).
    """
    ET = timezone(timedelta(hours=-5))
    et_now = datetime.now(ET)
    game_date = et_now - timedelta(days=1)
    return game_date.strftime("%Y-%m-%d")


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


def find_previous_snapshot(date_str):
    """Find the most recent snapshot BEFORE the given date."""
    if not DAILY_DIR.exists():
        return None
    
    target = datetime.strptime(date_str, "%Y-%m-%d")
    snapshots = sorted(DAILY_DIR.glob("*.json"), reverse=True)
    
    for filepath in snapshots:
        snap_date_str = filepath.stem  # filename without extension
        try:
            snap_date = datetime.strptime(snap_date_str, "%Y-%m-%d")
            if snap_date < target:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
        except ValueError:
            continue
    
    return None


def compute_weekly_ranking(today_str, game_days):
    """
    Compute weekly ranking using calendar-aware logic.
    
    - game_days: dict of {day_index: [event_ids]} for this week
    - Only days WITH scheduled games get points
    - Points = delta of 'total' between today's snapshot and previous snapshot
    """
    monday_str, sunday_str = get_week_bounds(today_str)
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")

    print(f"Computing weekly ranking for {monday_str} to {sunday_str}")
    print(f"  Game days this week: {sorted(game_days.keys())} (0=Mon..6=Sun)")

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

    # Build lookup: entry_id -> {day_str: total}
    entry_totals = {}  # entry_id -> {date: total}
    entry_info = {}    # entry_id -> {player_name, entry_name}

    for day_str, snapshot in daily_snapshots.items():
        for e in snapshot["entries"]:
            eid = e["entry"]
            entry_info[eid] = {
                "player_name": e["player_name"],
                "entry_name": e["entry_name"],
            }
            if eid not in entry_totals:
                entry_totals[eid] = {}
            entry_totals[eid][day_str] = e["total"]

    # Try to load a snapshot from before this week (for first day's delta)
    pre_week_snapshot = find_previous_snapshot(monday_str)
    pre_week_totals = {}
    if pre_week_snapshot:
        print(f"  Loaded pre-week snapshot: {pre_week_snapshot['date']}")
        for e in pre_week_snapshot["entries"]:
            pre_week_totals[e["entry"]] = e["total"]

    # Compute weekly data
    weekly_data = []

    for eid, info in entry_info.items():
        totals = entry_totals.get(eid, {})

        # Build day-by-day points array (Mon=0 to Sun=6)
        days_array = [None] * 7
        weekly_total = 0

        for i in range(7):
            day_dt = monday_dt + timedelta(days=i)
            day_str = day_dt.strftime("%Y-%m-%d")

            # If this day has no scheduled games, skip it (stays None)
            if i not in game_days:
                continue

            # If we don't have a snapshot for this day yet, skip
            if day_str not in totals:
                continue

            current_total = totals[day_str]

            # Find the previous snapshot's total for this entry
            prev_total = None

            # Look backwards through this week's snapshots
            for j in range(i - 1, -1, -1):
                prev_day = (monday_dt + timedelta(days=j)).strftime("%Y-%m-%d")
                if prev_day in totals:
                    prev_total = totals[prev_day]
                    break

            # If no previous snapshot in this week, use pre-week
            if prev_total is None and eid in pre_week_totals:
                prev_total = pre_week_totals[eid]

            if prev_total is not None:
                day_pts = (current_total - prev_total) // POINTS_DIVISOR
            else:
                # No reference point — can't calculate delta
                # This only happens for the very first snapshot ever
                day_pts = 0

            days_array[i] = day_pts
            weekly_total += day_pts

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

    # Compute movement
    yesterday_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    if yesterday_str in daily_snapshots and len(sorted_days) >= 2:
        # Rebuild yesterday's weekly totals
        yesterday_weekly = {}
        for eid in entry_info:
            totals = entry_totals.get(eid, {})
            yday_total = 0

            for i in range(7):
                day_dt = monday_dt + timedelta(days=i)
                day_str = day_dt.strftime("%Y-%m-%d")

                if day_str > yesterday_str:
                    break
                if i not in game_days:
                    continue
                if day_str not in totals:
                    continue

                current = totals[day_str]
                prev = None
                for j in range(i - 1, -1, -1):
                    prev_day = (monday_dt + timedelta(days=j)).strftime("%Y-%m-%d")
                    if prev_day in totals:
                        prev = totals[prev_day]
                        break
                if prev is None and eid in pre_week_totals:
                    prev = pre_week_totals[eid]

                if prev is not None:
                    yday_total += (current - prev) // POINTS_DIVISOR

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


def build_output(weekly_data, today_str, last_updated, game_days, week_number):
    """Build the final JSON output for the frontend."""
    monday_str, sunday_str = get_week_bounds(today_str)
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")

    today_index = today_dt.weekday()

    day_labels = []
    for i in range(7):
        day_dt = monday_dt + timedelta(days=i)
        day_labels.append(day_dt.strftime("%a"))

    # Mark which days have games
    has_games = [i in game_days for i in range(7)]

    output = {
        "meta": {
            "week_number": week_number,
            "week_start": monday_str,
            "week_end": sunday_str,
            "today": today_str,
            "today_index": today_index,
            "day_labels": day_labels,
            "has_games": has_games,
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
    print("NBA Fantasy Salary Cup — Daily Scraper v4")
    print("=" * 60)

    today_str = get_game_date_str()
    monday_str, sunday_str = get_week_bounds(today_str)
    print(f"Game date: {today_str}")
    print(f"Week: {monday_str} to {sunday_str}")

    # Fetch events calendar
    events = fetch_events()

    # Save events locally for reference
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False)

    # Determine game days for this week
    game_days = get_game_dates_for_week(events, monday_str, sunday_str)
    print(f"Game days this week (0=Mon..6=Sun): {sorted(game_days.keys())}")

    for idx in sorted(game_days.keys()):
        day_dt = datetime.strptime(monday_str, "%Y-%m-%d") + timedelta(days=idx)
        day_name = day_dt.strftime("%A %d %b")
        print(f"  {day_name}: events {game_days[idx]}")

    # Calculate week number
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")
    weeks_diff = (monday_dt - SEASON_START).days // 7
    nba_week = 1 + weeks_diff

    # Also try to get Jornada number from events
    jornada = get_jornada_number(events, monday_str, sunday_str)
    if jornada:
        nba_week = jornada
        print(f"Jornada: {jornada}")
    else:
        print(f"Week number (calculated): {nba_week}")

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
    print(f"  total={top['total']} ({top['total'] // POINTS_DIVISOR} real)")

    # Save daily snapshot
    save_daily_snapshot(entries, today_str)

    # Compute weekly ranking
    weekly_data = compute_weekly_ranking(today_str, game_days)

    if weekly_data:
        output = build_output(weekly_data, today_str, last_updated, game_days, nba_week)

        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False)

        print(f"\nOutput saved: {OUTPUT_FILE}")
        print(f"Total players in ranking: {len(weekly_data)}")
        print(f"Top 5 weekly:")
        for e in weekly_data[:5]:
            days_str = [str(d) if d is not None else "—" for d in e["days"]]
            print(f"  #{e['rank']} {e['player_name']} ({e['entry_name']}) — "
                  f"Week: {e['total']} pts — Days: [{', '.join(days_str)}]")
    else:
        print("Could not compute weekly ranking.")

    print("\nDone!")


if __name__ == "__main__":
    main()
