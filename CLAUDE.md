# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a personal collection of AI agents built with the Anthropic Python SDK. Each agent lives in its own subdirectory under `agents/` with its own dependencies and `.env`.

## Agents

### `agents/interview-agent/`
A CLI interview simulator. Runs a streaming multi-turn conversation via `anthropic.Anthropic().messages.stream()` with prompt caching on the system prompt (`cache_control: ephemeral`). Uses `claude-sonnet-4-6`.

**Run:**
```bash
cd agents/interview-agent
pip install -r requirements.txt
python interview_agent.py
```

### `agents/trainingagent/`
A marathon training coach agent. Pulls data from Strava, Garmin Connect, and Notion, then uses `anthropic.beta.messages.tool_runner` with `@beta_tool`-decorated Python functions as tools. Uses `claude-opus-4-7`.

**Run:**
```bash
cd agents/trainingagent
cp .env.example .env   # fill in credentials
pip install -r requirements.txt
python strava_auth.py  # one-time Strava OAuth — populates STRAVA_REFRESH_TOKEN in .env
python main.py                    # review last 14 days, update plan
python main.py --days 7           # shorter window
python main.py --dry-run          # print updated plan without saving to Notion
python main.py --no-garmin        # skip Garmin (use when rate-limited)
python main.py --note "on vacation this week"
```

**Required env vars** (see `.env.example`): `ANTHROPIC_API_KEY`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `NOTION_TOKEN`, `NOTION_PAGE_ID`.

## Key Architecture Patterns

- **`@beta_tool` decorator** — `main.py` uses `anthropic.beta_tool` to expose plain Python functions as Claude tools. The decorator infers the tool schema from the function signature and docstring; no manual JSON schema needed.
- **`tool_runner`** — `client.beta.messages.tool_runner(...)` drives the agentic loop automatically: it calls tools, feeds results back, and iterates until Claude stops calling tools. Iterate over the runner to stream intermediate text.
- **Prompt caching** — the interview agent caches its large system prompt with `cache_control: {"type": "ephemeral"}` to reduce latency and cost on repeated turns.
- **Notion as primary store** — the training agent reads/writes the live training plan and workout log via `notion_plan.py`; `training_plan.md` is a local backup only.
