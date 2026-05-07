import os
from pathlib import Path
from datetime import datetime, timedelta
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

TOKEN_DIR = str(Path("~/.garminconnect").expanduser())
_client: Garmin | None = None


def _get_client() -> Garmin:
    global _client
    if _client:
        return _client

    # Try saved tokens first
    try:
        client = Garmin()
        client.login(TOKEN_DIR)
        _client = client
        return _client
    except (GarminConnectAuthenticationError, GarminConnectConnectionError):
        pass

    # Fall back to credential login
    client = Garmin(
        email=os.environ["GARMIN_EMAIL"],
        password=os.environ["GARMIN_PASSWORD"],
        prompt_mfa=lambda: input("Garmin MFA code: ").strip(),
    )
    client.login(TOKEN_DIR)
    _client = client
    return _client


def get_recent_metrics(days: int = 14) -> list[dict]:
    client = _get_client()
    metrics = []

    for i in range(days - 1, -1, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        row: dict = {"date": date}

        try:
            stats = client.get_stats(date)
            row["total_steps"] = stats.get("totalSteps")
            row["avg_stress"] = stats.get("averageStressLevel")
            row["rest_hr"] = stats.get("restingHeartRate")
        except Exception:
            pass

        try:
            sleep = client.get_sleep_data(date)
            daily = sleep.get("dailySleepDTO", {})
            seconds = daily.get("sleepTimeSeconds", 0)
            row["sleep_hours"] = round(seconds / 3600, 1) if seconds else None
            row["sleep_score"] = daily.get("sleepScores", {}).get("overall", {}).get("value")
        except Exception:
            pass

        try:
            hrv = client.get_hrv_data(date)
            summary = hrv.get("hrvSummary", {})
            row["hrv_weekly_avg"] = summary.get("weeklyAvg")
            row["hrv_last_night"] = summary.get("lastNight")
            row["hrv_status"] = summary.get("hrvStatus")
        except Exception:
            pass

        try:
            bb = client.get_body_battery(date, date)
            if bb:
                row["body_battery_high"] = max((r.get("charged", 0) for r in bb), default=None)
        except Exception:
            pass

        metrics.append(row)

    return metrics
