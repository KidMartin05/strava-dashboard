import os
import json
import math
from datetime import datetime, timedelta, timezone
from collections import defaultdict


import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

# uvicorn app.main:app --reload

load_dotenv()

app = FastAPI()

templates = Jinja2Templates(directory="templates")

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

# Load saved tokens from tokens.json if it exists
if os.path.exists("tokens.json"):
    with open("tokens.json", "r") as f:
        TOKENS = json.load(f)
else:
    TOKENS = {}

ATHLETES = {}
ACTIVITIES = {}


def parse_strava_datetime(dt_str: str):
    return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ")

def meters_to_miles(meters: float) -> float:
    return meters * 0.000621371


def mps_to_min_per_mile(speed_mps: float):
    if not speed_mps or speed_mps <= 0:
        return None
    seconds_per_mile = 1609.344 / speed_mps
    minutes = int(seconds_per_mile // 60)
    seconds = int(round(seconds_per_mile % 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}"


def format_duration(total_seconds: int) -> str:
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def auth_headers(access_token: str):
    return {"Authorization": f"Bearer {access_token}"}


def refresh_access_token_if_needed(athlete_id: str):
    token_data = TOKENS.get(athlete_id)
    if not token_data or not isinstance(token_data, dict):
        return None

    expires_at = token_data.get("expires_at", 0)
    now_ts = int(datetime.now(timezone.utc).timestamp())

    if now_ts < expires_at - 60:
        return token_data["access_token"]

    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
        },
        timeout=20,
    )
    response.raise_for_status()
    new_token_data = response.json()

    TOKENS[athlete_id] = {
        "access_token": new_token_data["access_token"],
        "refresh_token": new_token_data["refresh_token"],
        "expires_at": new_token_data["expires_at"],
    }

    with open("tokens.json", "w") as f:
        json.dump(TOKENS, f, indent=4)

    return new_token_data["access_token"]


def get_logged_in_athlete(access_token: str):
    response = requests.get(
        f"{STRAVA_API_BASE}/athlete",
        headers=auth_headers(access_token),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def get_athlete_stats(access_token: str, athlete_id: int):
    response = requests.get(
        f"{STRAVA_API_BASE}/athletes/{athlete_id}/stats",
        headers=auth_headers(access_token),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def get_all_activities(access_token: str, per_page: int = 100, max_pages: int = 10):
    all_items = []

    for page in range(1, max_pages + 1):
        response = requests.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers=auth_headers(access_token),
            params={"page": page, "per_page": per_page},
            timeout=20,
        )
        response.raise_for_status()
        items = response.json()

        if not items:
            break

        all_items.extend(items)

        if len(items) < per_page:
            break

    return all_items


def compute_dashboard_stats(activities, official_stats=None):
    run_activities = [a for a in activities if a.get("sport_type") == "Run"]

    total_runs = len(run_activities)
    total_miles = round(sum(meters_to_miles(a.get("distance", 0)) for a in run_activities), 2)
    total_elevation = round(sum(a.get("total_elevation_gain", 0) for a in run_activities), 1)

    last_run = run_activities[0] if run_activities else None

    longest_run = None
    if run_activities:
        longest_run = max(run_activities, key=lambda a: a.get("distance", 0))

    avg_speed_values = [a.get("average_speed") for a in run_activities if a.get("average_speed")]
    avg_speed = sum(avg_speed_values) / len(avg_speed_values) if avg_speed_values else None

    weekly_totals = defaultdict(float)
    monthly_totals = defaultdict(float)

    for activity in run_activities:
        start_date = activity.get("start_date")
        if not start_date:
            continue

        dt = parse_strava_datetime(start_date)
        year, week_num, _ = dt.isocalendar()
        weekly_key = f"{year}-W{week_num:02d}"
        monthly_key = f"{dt.year}-{dt.month:02d}"

        weekly_totals[weekly_key] += meters_to_miles(activity.get("distance", 0))
        monthly_totals[monthly_key] += meters_to_miles(activity.get("distance", 0))

    current_streak = calculate_run_streak(run_activities)

    ytd_miles = None
    if official_stats:
        ytd_meters = official_stats.get("ytd_run_totals", {}).get("distance", 0)
        ytd_miles = round(meters_to_miles(ytd_meters), 2)

    return {
        "total_runs": total_runs,
        "total_miles": total_miles,
        "total_elevation_meters": total_elevation,
        "average_pace": mps_to_min_per_mile(avg_speed) if avg_speed else None,
        "current_streak_days": current_streak,
        "ytd_miles": ytd_miles,
        "last_run": summarize_run(last_run) if last_run else None,
        "longest_run": summarize_run(longest_run) if longest_run else None,
        "weekly_totals": dict(sorted(weekly_totals.items())),
        "monthly_totals": dict(sorted(monthly_totals.items())),
    }


def summarize_run(activity):
    if not activity:
        return None

    return {
        "name": activity.get("name"),
        "date": activity.get("start_date_local"),
        "distance_miles": round(meters_to_miles(activity.get("distance", 0)), 2),
        "moving_time": format_duration(activity.get("moving_time", 0)),
        "pace": mps_to_min_per_mile(activity.get("average_speed")),
        "elevation_gain_m": round(activity.get("total_elevation_gain", 0), 1),
    }


def calculate_run_streak(run_activities):
    if not run_activities:
        return 0

    run_days = set()
    for activity in run_activities:
        start_date = activity.get("start_date")
        if not start_date:
            continue
        dt = parse_strava_datetime(start_date).date()
        run_days.add(dt)

    streak = 0
    today = datetime.now(timezone.utc).date()

    check_day = today
    while check_day in run_days:
        streak += 1
        check_day -= timedelta(days=1)

    if streak == 0:
        yesterday = today - timedelta(days=1)
        check_day = yesterday
        while check_day in run_days:
            streak += 1
            check_day -= timedelta(days=1)

    return streak


@app.get("/", response_class=HTMLResponse)
def home():
    athlete_id = None

    for key, value in TOKENS.items():
        if isinstance(value, dict) and "access_token" in value:
            athlete_id = key
            break

    if athlete_id:
        return RedirectResponse(url=f"/dashboard/{athlete_id}/pretty")

    return """
    <html>
        <head>
            <title>Strava Stats App</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; }
                a.button {
                    display: inline-block;
                    padding: 12px 18px;
                    background: #fc4c02;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: bold;
                }
            </style>
        </head>
        <body>
            <h1>Strava Stats App</h1>
            <p>Connect your Strava account to view your dashboard.</p>
            <a class="button" href="/login">Connect with Strava</a>
        </body>
    </html>
    """


@app.get("/login")
def login():
    scope = "read,activity:read_all"
    url = (
        f"{STRAVA_AUTH_URL}"
        f"?client_id={STRAVA_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={STRAVA_REDIRECT_URI}"
        f"&approval_prompt=force"
        f"&scope={scope}"
    )
    return RedirectResponse(url=url)


@app.get("/auth/callback")
def auth_callback(code: str):
    token_response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    token_response.raise_for_status()
    token_data = token_response.json()

    access_token = token_data["access_token"]
    athlete = token_data["athlete"]
    athlete_id = str(athlete["id"])

    TOKENS[athlete_id] = {
        "access_token": access_token,
        "refresh_token": token_data["refresh_token"],
        "expires_at": token_data["expires_at"],
    }

    with open("tokens.json", "w") as f:
        json.dump(TOKENS, f, indent=4)

    ATHLETES[athlete_id] = athlete

    return RedirectResponse(url=f"/dashboard/{athlete_id}/pretty")


@app.get("/dashboard/{athlete_id}")
def dashboard(athlete_id: str):
    access_token = refresh_access_token_if_needed(athlete_id)
    if not access_token:
        return JSONResponse({"error": "No token found for this athlete."}, status_code=404)

    athlete = get_logged_in_athlete(access_token)
    official_stats = get_athlete_stats(access_token, int(athlete_id))
    activities = get_all_activities(access_token)

    ACTIVITIES[athlete_id] = activities
    computed_stats = compute_dashboard_stats(activities, official_stats)

    return {
        "athlete": {
            "id": athlete.get("id"),
            "firstname": athlete.get("firstname"),
            "lastname": athlete.get("lastname"),
            "city": athlete.get("city"),
            "state": athlete.get("state"),
            "country": athlete.get("country"),
        },
        "official_strava_stats": official_stats,
        "computed_dashboard_stats": computed_stats,
    }


@app.get("/dashboard/{athlete_id}/pretty", response_class=HTMLResponse)
def pretty_dashboard(athlete_id: str):
    access_token = refresh_access_token_if_needed(athlete_id)
    if not access_token:
        return HTMLResponse("<h1>No athlete token found.</h1>", status_code=404)

    athlete = get_logged_in_athlete(access_token)
    activities = get_all_activities(access_token)
    official_stats = get_athlete_stats(access_token, int(athlete_id))
    stats = compute_dashboard_stats(activities, official_stats)

    last_run_html = "<p>No runs found.</p>"
    if stats["last_run"]:
        last_run_html = f"""
        <p><strong>{stats['last_run']['name']}</strong></p>
        <p>{stats['last_run']['distance_miles']} miles</p>
        <p>{stats['last_run']['moving_time']}</p>
        <p>Pace: {stats['last_run']['pace'] or 'N/A'}</p>
        """

    longest_run_html = "<p>No runs found.</p>"
    if stats["longest_run"]:
        longest_run_html = f"""
        <p><strong>{stats['longest_run']['name']}</strong></p>
        <p>{stats['longest_run']['distance_miles']} miles</p>
        <p>{stats['longest_run']['moving_time']}</p>
        <p>Pace: {stats['longest_run']['pace'] or 'N/A'}</p>
        """

    return f"""
    <html>
        <head>
            <title>Strava Dashboard</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background: #f7f7f7;
                    max-width: 1100px;
                    margin: 30px auto;
                    padding: 20px;
                }}
                .grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 16px;
                }}
                .card {{
                    background: white;
                    border-radius: 14px;
                    padding: 18px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                }}
                h1, h2 {{
                    margin-bottom: 8px;
                }}
                .muted {{
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <h1>{athlete.get('firstname', '')} {athlete.get('lastname', '')}'s Strava Dashboard</h1>
            <p class="muted">{athlete.get('city', '')}, {athlete.get('state', '')}, {athlete.get('country', '')}</p>

            <div class="grid">
                <div class="card">
                    <h2>Total Runs</h2>
                    <p>{stats['total_runs']}</p>
                </div>
                <div class="card">
                    <h2>Total Miles</h2>
                    <p>{stats['total_miles']}</p>
                </div>
                <div class="card">
                    <h2>Miles This Year</h2>
                    <p>{stats['ytd_miles']}</p>
                </div>
                <div class="card">
                    <h2>Average Pace</h2>
                    <p>{stats['average_pace'] or 'N/A'}</p>
                </div>
                <div class="card">
                    <h2>Current Streak</h2>
                    <p>{stats['current_streak_days']} days</p>
                </div>
                <div class="card">
                    <h2>Last Run</h2>
                    {last_run_html}
                </div>
                <div class="card">
                    <h2>Longest Run</h2>
                    {longest_run_html}
                </div>
            </div>

            <p style="margin-top: 24px;">
                JSON view: <a href="/dashboard/{athlete_id}">/dashboard/{athlete_id}</a>
            </p>
        </body>
    </html>
    """