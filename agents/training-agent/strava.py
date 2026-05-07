import os
import requests
from datetime import datetime, timedelta

STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

_access_token: str | None = None


def _get_access_token() -> str:
    global _access_token
    if _access_token:
        return _access_token

    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    data = resp.json()
    _access_token = data["access_token"]
    # Persist the new refresh token for next run
    os.environ["STRAVA_REFRESH_TOKEN"] = data["refresh_token"]
    return _access_token


def get_recent_runs(days: int = 14) -> list[dict]:
    after = int((datetime.now() - timedelta(days=days)).timestamp())
    headers = {"Authorization": f"Bearer {_get_access_token()}"}
    resp = requests.get(
        f"{STRAVA_API_BASE}/athlete/activities",
        headers=headers,
        params={"after": after, "per_page": 50},
    )
    resp.raise_for_status()

    activities = []
    for a in resp.json():
        activity_type = a.get("type", "")

        distance_mi = round(a["distance"] / 1609.34, 2) if a.get("distance") else 0
        duration_min = round(a["moving_time"] / 60, 1)
        pace_min_per_mi = round(duration_min / distance_mi, 2) if distance_mi else None

        activities.append({
            "date": a["start_date_local"][:10],
            "type": activity_type,
            "name": a.get("name", activity_type),
            "distance_mi": distance_mi,
            "duration_min": duration_min,
            "pace_min_per_mi": pace_min_per_mi,
            "avg_hr": a.get("average_heartrate"),
            "max_hr": a.get("max_heartrate"),
            "elevation_m": a.get("total_elevation_gain"),
            "suffer_score": a.get("suffer_score"),
            "perceived_exertion": a.get("perceived_exertion"),
        })

    return sorted(activities, key=lambda a: a["date"])
