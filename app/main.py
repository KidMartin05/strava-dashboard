import os
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

TOKENS_FILE = "tokens.json"

if os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "r") as f:
        TOKENS = json.load(f)
else:
    TOKENS = {}

ATHLETES = {}
ACTIVITIES = {}


def save_tokens():
    with open(TOKENS_FILE, "w") as f:
        json.dump(TOKENS, f, indent=4)


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
    save_tokens()

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


def is_run_activity(activity):
    sport_type = activity.get("sport_type")
    activity_type = activity.get("type")
    run_types = {"Run", "TrailRun", "VirtualRun"}
    return sport_type in run_types or activity_type in run_types


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
        start_date_local = activity.get("start_date_local")
        if not start_date_local:
            continue

        dt = parse_strava_datetime(start_date_local).date()
        run_days.add(dt)

    if not run_days:
        return 0

    today = datetime.now().date()
    streak = 0
    check_day = today

    while check_day in run_days:
        streak += 1
        check_day -= timedelta(days=1)

    if streak == 0:
        check_day = today - timedelta(days=1)
        while check_day in run_days:
            streak += 1
            check_day -= timedelta(days=1)

    return streak


def compute_dashboard_stats(activities, official_stats=None):
    run_activities = [a for a in activities if is_run_activity(a)]

    total_runs = len(run_activities)
    total_miles = round(sum(meters_to_miles(a.get("distance", 0)) for a in run_activities), 2)
    total_elevation = round(sum(a.get("total_elevation_gain", 0) for a in run_activities), 1)

    last_run = run_activities[0] if run_activities else None
    longest_run = max(run_activities, key=lambda a: a.get("distance", 0)) if run_activities else None

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


def compute_daily_miles_this_year(activities):
    current_year = datetime.now(timezone.utc).year
    daily_totals = defaultdict(float)

    for activity in activities:
        if not is_run_activity(activity):
            continue

        start_date_local = activity.get("start_date_local")
        if not start_date_local:
            continue

        dt = parse_strava_datetime(start_date_local)
        if dt.year != current_year:
            continue

        day_key = dt.date().isoformat()
        daily_totals[day_key] += meters_to_miles(activity.get("distance", 0))

    return dict(sorted(daily_totals.items()))


def compute_weekly_miles_this_year(activities):
    current_year = datetime.now(timezone.utc).year
    weekly_totals = defaultdict(float)

    for activity in activities:
        if not is_run_activity(activity):
            continue

        start_date_local = activity.get("start_date_local")
        if not start_date_local:
            continue

        dt = parse_strava_datetime(start_date_local)
        if dt.year != current_year:
            continue

        year, week_num, _ = dt.isocalendar()
        week_key = f"{year}-W{week_num:02d}"
        weekly_totals[week_key] += meters_to_miles(activity.get("distance", 0))

    return dict(sorted(weekly_totals.items()))


def compute_monthly_miles_this_year(activities):
    current_year = datetime.now(timezone.utc).year
    monthly_totals = defaultdict(float)

    for activity in activities:
        if not is_run_activity(activity):
            continue

        start_date_local = activity.get("start_date_local")
        if not start_date_local:
            continue

        dt = parse_strava_datetime(start_date_local)
        if dt.year != current_year:
            continue

        month_key = f"{dt.year}-{dt.month:02d}"
        monthly_totals[month_key] += meters_to_miles(activity.get("distance", 0))

    return dict(sorted(monthly_totals.items()))


def get_heat_level(miles):
    if miles == 0:
        return "level-0"
    if miles < 3:
        return "level-1"
    if miles < 6:
        return "level-2"
    if miles < 9:
        return "level-3"
    return "level-4"


def build_daily_heatmap_data(daily_miles, year):
    items = []
    current_day = datetime(year, 1, 1).date()
    end_of_year = datetime(year, 12, 31).date()

    while current_day <= end_of_year:
        day_str = current_day.isoformat()
        miles = round(daily_miles.get(day_str, 0), 2)
        items.append(
            {
                "label": day_str,
                "miles": miles,
                "level": get_heat_level(miles),
            }
        )
        current_day += timedelta(days=1)

    return items


def build_weekly_heatmap_data(weekly_miles, year):
    items = []

    for week_num in range(1, 54):
        week_key = f"{year}-W{week_num:02d}"
        miles = round(weekly_miles.get(week_key, 0), 2)
        items.append(
            {
                "label": f"Week {week_num}",
                "miles": miles,
                "level": get_heat_level(miles),
            }
        )

    return items


def build_monthly_heatmap_data(monthly_miles, year):
    items = []
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]

    for month_num in range(1, 13):
        month_key = f"{year}-{month_num:02d}"
        miles = round(monthly_miles.get(month_key, 0), 2)
        month_name = month_names[month_num - 1]

        items.append(
            {
                "label": month_name,
                "short_label": month_name[:3],
                "miles": miles,
                "level": get_heat_level(miles),
            }
        )

    return items


@app.get("/")
def home(request: Request):
    athlete_id = None

    for key, value in TOKENS.items():
        if isinstance(value, dict) and "access_token" in value:
            athlete_id = key
            break

    if athlete_id:
        return RedirectResponse(url=f"/dashboard/{athlete_id}/pretty")

    return templates.TemplateResponse(
        "home.html",
        {"request": request},
    )


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

    athlete = token_data["athlete"]
    athlete_id = str(athlete["id"])

    TOKENS[athlete_id] = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "expires_at": token_data["expires_at"],
    }
    save_tokens()

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


@app.get("/dashboard/{athlete_id}/pretty")
def pretty_dashboard(request: Request, athlete_id: str):
    access_token = refresh_access_token_if_needed(athlete_id)
    if not access_token:
        return JSONResponse({"error": "No athlete token found."}, status_code=404)

    athlete = get_logged_in_athlete(access_token)
    activities = get_all_activities(access_token)
    official_stats = get_athlete_stats(access_token, int(athlete_id))
    stats = compute_dashboard_stats(activities, official_stats)

    current_year = datetime.now(timezone.utc).year

    daily_miles = compute_daily_miles_this_year(activities)
    weekly_miles = compute_weekly_miles_this_year(activities)
    monthly_miles = compute_monthly_miles_this_year(activities)

    daily_heatmap = build_daily_heatmap_data(daily_miles, current_year)
    weekly_heatmap = build_weekly_heatmap_data(weekly_miles, current_year)
    monthly_heatmap = build_monthly_heatmap_data(monthly_miles, current_year)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "athlete_id": athlete_id,
            "athlete": athlete,
            "stats": stats,
            "official_stats": official_stats,
            "current_year": current_year,
            "daily_heatmap": daily_heatmap,
            "weekly_heatmap": weekly_heatmap,
            "monthly_heatmap": monthly_heatmap,
        },
    )