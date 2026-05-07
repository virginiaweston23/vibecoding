"""
Marathon training agent — pulls Strava + Garmin data, refines your training plan.

Usage:
    python main.py               # review last 14 days, update next week
    python main.py --days 7      # shorter review window
    python main.py --dry-run     # print the updated plan without saving
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

import anthropic
from anthropic import beta_tool

PLAN_FILE = Path("training_plan.md")

# ── Tool definitions ──────────────────────────────────────────────────────────

@beta_tool
def get_strava_runs(days: int = 14) -> str:
    """
    Fetch recent runs from Strava.

    Returns a JSON list of runs, each with date, distance_mi, duration_min,
    pace_min_per_mi, avg_hr, max_hr, elevation_m, suffer_score,
    and perceived_exertion (1–10 scale, may be null).

    Args:
        days: How many days back to look (default 14).
    """
    from strava import get_recent_runs
    runs = get_recent_runs(days)
    return json.dumps(runs, indent=2)


@beta_tool
def get_garmin_metrics(days: int = 14) -> str:
    """
    Fetch daily recovery and readiness metrics from Garmin Connect.

    Returns a JSON list of daily records, each with date, sleep_hours,
    sleep_score, hrv_last_night, hrv_weekly_avg, hrv_status (BALANCED /
    UNBALANCED / POOR), body_battery_high, rest_hr, and avg_stress.

    Args:
        days: How many days back to look (default 14).
    """
    try:
        from garmin import get_recent_metrics
        metrics = get_recent_metrics(days)
        return json.dumps(metrics, indent=2)
    except Exception as e:
        return f"Garmin unavailable ({e}). Proceed with Strava data only."


@beta_tool
def get_training_log(days: int = 14) -> str:
    """
    Fetch recent rows from the Notion Training Log database.

    Returns a JSON list of daily workout rows for the past N days, each with:
    page_id, date, session, week, phase, day_type, planned_workout,
    planned_miles, completed, actual_miles, avg_hr, pace, hrv_status,
    sleep_score, body_battery, notes.

    Use page_id with log_workout to update a row.

    Args:
        days: How many days back to look (default 14).
    """
    from notion_plan import get_training_log as _get_log
    import json
    return json.dumps(_get_log(days), indent=2)


@beta_tool
def log_workout(
    page_id: str,
    completed: bool,
    actual_miles: float | None = None,
    avg_hr: float | None = None,
    pace: str | None = None,
    hrv_status: str | None = None,
    sleep_score: float | None = None,
    body_battery: float | None = None,
    notes: str | None = None,
) -> str:
    """
    Update a Training Log row with actual performance data from Strava/Garmin.

    Args:
        page_id: The Notion page ID of the workout row (from get_training_log).
        completed: Whether the workout was completed.
        actual_miles: Actual miles run (omit for strength/cross-train).
        avg_hr: Average heart rate in bpm.
        pace: Actual pace as a string, e.g. "9:42/mi".
        hrv_status: One of "Balanced", "Unbalanced", "Poor".
        sleep_score: Garmin sleep score (0–100).
        body_battery: Garmin body battery high for the day (0–100).
        notes: Coach or athlete notes for this session.
    """
    from notion_plan import update_workout_row
    update_workout_row(
        page_id,
        completed=completed,
        actual_miles=actual_miles,
        avg_hr=avg_hr,
        pace=pace,
        hrv_status=hrv_status,
        sleep_score=sleep_score,
        body_battery=body_battery,
        notes=notes,
    )
    return f"Updated workout row {page_id}."


@beta_tool
def read_training_plan() -> str:
    """Read the current marathon training plan from Notion."""
    try:
        from notion_plan import read_plan
        return read_plan()
    except Exception as e:
        # Fall back to local file if Notion is unavailable
        if PLAN_FILE.exists():
            return PLAN_FILE.read_text()
        return f"Could not read plan from Notion ({e}) and no local fallback found."


@beta_tool
def update_training_plan(updated_plan: str, summary_of_changes: str) -> str:
    """
    Write the refined training plan back to Notion and print a summary of changes.

    Args:
        updated_plan: The full updated markdown content of the plan.
        summary_of_changes: 2–4 bullet points explaining what was changed and why.
    """
    if DRY_RUN:
        print("\n── UPDATED PLAN (dry run — not saved) ──────────────────")
        print(updated_plan)
        print("────────────────────────────────────────────────────────\n")
    else:
        from notion_plan import update_plan
        update_plan(updated_plan)
        # Keep local file in sync as backup
        PLAN_FILE.write_text(updated_plan)

    print("\n── CHANGES MADE ────────────────────────────────────────")
    print(summary_of_changes)
    print("────────────────────────────────────────────────────────\n")
    return "Plan updated successfully."


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a marathon running coach working with a specific athlete.
Your job is to review their recent training data and refine the upcoming week of
their plan. Here is everything you need to know about this athlete:

## Race & Goal
- Race: NYC Marathon, November 1, 2026
- A goal: 3:38 finish (8:20/mi race pace)
- Range: 3:30–3:45
- Current block: base-building plan April 20 – August 3, then Pfitzinger 18/55

## Pace Zones (all paces in min/mile)
- Easy / long run: 9:30–10:00/mi
- Recovery run: 10:00–10:30/mi
- Lactate threshold (LT): 8:00–8:20/mi (exact target depends on workout letter)
- RULE: Never run medium. Every run is either easy/recovery OR a structured LT
  workout. No "moderate effort" or "comfortably hard" easy days.

## LT Workout Library (named A–E, referenced in the plan)
When assigning or adjusting LT sessions, use these exact names:
- Workout A: 1.5mi WU + 15min threshold + 90s jog + 10min threshold + 1.5mi CD (~5–6 mi total). Use in cutback weeks.
- Workout B: 1.5mi WU + 20min threshold + 90s jog + 15min threshold + 1.5mi CD (~7 mi). Weeks 5–6.
- Workout C: 1.5mi WU + 20min + 60s + 20min + 60s + 10min threshold + 1.5mi CD (~8 mi). Weeks 8–9.
- Workout D: 2mi WU + 25min + 60s + 20min + 60s + 10min threshold + 2mi CD (~9 mi). Weeks 10–15.
- Workout E: 1.5mi WU + 15min + 90s + 15min threshold + 1.5mi CD (~6 mi). Friday 2nd quality session only, Phase 3.
- If downgrading due to fatigue: drop one letter (C→B, B→A). Never upgrade mid-week.

## Athlete Lifestyle Context
- Athlete parties on weekends — expect elevated resting HR, suppressed HRV, and lower body battery on Monday and Tuesday
- Do NOT flag Monday/Tuesday recovery metrics as a training problem; this is normal baseline for this athlete
- Monday easy runs are important for getting back on track — keep them easy, don't cut them
- If Saturday long run data shows elevated HR, consider whether it may be alcohol-related before adjusting the plan

## Injury History — Peroneal Tendon (HIGH PRIORITY)
- History of peroneal tendon issues on the lateral ankle.
- HARD RULES — never override these:
  1. Weekly mileage must never increase more than 10% from the prior completed week.
  2. Cutback weeks at plan weeks 7 and 14 are mandatory — do not skip or delay them.
  3. At any sign of lateral ankle pain: replace the run with pool running or cycling immediately.
  4. In Phase 3, Workout E (Friday) is always the first session to cut if peroneal flares.
- Strength sessions (2x/week) include mandatory ankle/peroneal work — do not remove them.

## What to look for in training data
- Easy runs drifting above 155 bpm avg HR = running too hard, flag it
- Weekly mileage vs. target — if >10% below, do not make it up; continue as planned
- HRV: if POOR or UNBALANCED on consecutive days, downgrade Wednesday LT by one letter
- Body battery below 40 on a key session day = consider swapping to easy run
- Sleep score below 60 = note it; below 55 on LT day = downgrade the session
- Missing long run = do not reschedule mid-week; note it and adjust next week's plan

## Workflow each run
1. Call get_training_log (14 days) to see planned vs. completed sessions and existing metrics.
2. Call get_strava_runs and get_garmin_metrics to fetch fresh data.
3. Match each Strava run to its Training Log row by date and call log_workout to fill in
   actual_miles, avg_hr, pace, hrv_status, sleep_score, body_battery. Mark completed=True.
   For rest/strength days with no run, mark completed based on whether an entry exists.
4. Read the plan, analyze trends across the log, then update next week if needed.

## How to present your output
- Keep the existing plan table format (markdown table with Day / Type / Workout columns)
- Preserve all phases, weeks, and Garmin workout sections already in the plan
- Only modify the upcoming week — do not rewrite the whole plan
- CRITICAL: preserve every section, week, and table that already exists in the plan — do NOT summarize, condense, or omit any weeks or Garmin workout details. The plan must come back at least as long as it went in. If a section is unchanged, copy it exactly as-is.
- End with a "Coach's notes" section: 2–5 bullets explaining what you changed and why
- Be direct. Skip preamble. If the data looks fine and no changes are needed, say so.

Today's date: {today}""".format(today=__import__('datetime').date.today().strftime("%B %d, %Y"))


# ── Main ──────────────────────────────────────────────────────────────────────

DRY_RUN = False
NO_GARMIN = False


def main():
    global DRY_RUN, NO_GARMIN

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-garmin", action="store_true", help="Skip Garmin (use when rate limited)")
    parser.add_argument("--note", type=str, default="", help="Any context the coach should know (e.g. 'I was on vacation')")
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    NO_GARMIN = args.no_garmin

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Missing ANTHROPIC_API_KEY in .env")

    print(f"Reviewing last {args.days} days of training data...")
    if NO_GARMIN:
        print("(Garmin skipped — Strava only)\n")
    if DRY_RUN:
        print("(dry run — plan will not be saved)\n")

    client = anthropic.Anthropic()

    tools = [get_strava_runs, get_training_log, log_workout, read_training_plan, update_training_plan]
    if not NO_GARMIN:
        tools.insert(1, get_garmin_metrics)

    data_sources = "Strava" if NO_GARMIN else "Strava and Garmin"

    runner = client.beta.messages.tool_runner(
        model="claude-opus-4-7",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=[{
            "role": "user",
            "content": (
                f"Please do the following in order:\n"
                f"1. Fetch the Training Log (last {args.days} days) to see what was planned.\n"
                f"2. Pull fresh data from {data_sources}.\n"
                f"3. For each run in Strava, find its matching Training Log row by date and "
                f"call log_workout to fill in actual miles, avg HR, pace, and mark it completed. "
                f"Also fill in HRV status, sleep score, and body battery from Garmin where available.\n"
                f"4. Read the training plan, analyze trends, and update next week's workouts "
                f"if the data warrants any changes.\n"
                f"5. End with Coach's notes explaining what you logged and any adjustments."
                + (f"\n\nAthlete note: {args.note}" if args.note else "")
            )
        }],
    )

    for message in runner:
        # Stream any text Claude produces while reasoning
        for block in message.content:
            if hasattr(block, "text") and block.type == "text":
                print(block.text)


if __name__ == "__main__":
    main()
