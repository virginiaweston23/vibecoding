"""
Notion integration for the marathon training agent.

Two things live in Notion:
  1. Plan page  — the markdown reference plan (read/write)
  2. Training Log database — daily workout rows (read/update)
"""
import os
from datetime import date, timedelta
from notion_client import Client

TRAINING_LOG_DB = "e1ef8ed86f2a4137a0158fae426d1cf9"
TRAINING_LOG_DS = "7b5ab04e-2514-4bf4-afa1-d0c40f968e81"  # data source (collection) ID

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if not _client:
        _client = Client(auth=os.environ["NOTION_TOKEN"])
    return _client


def _plan_page_id() -> str:
    pid = os.environ.get("NOTION_PAGE_ID", "")
    if not pid:
        raise ValueError("NOTION_PAGE_ID not set in environment")
    return pid.replace("-", "")


# ── Plan page (markdown reference) ───────────────────────────────────────────

def read_plan() -> str:
    notion = _get_client()
    pid = _plan_page_id()

    blocks = []
    cursor = None
    while True:
        kwargs = {"block_id": pid, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.blocks.children.list(**kwargs)
        blocks.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    lines = []
    for block in blocks:
        bt = block["type"]
        if bt == "child_database":
            continue  # skip the embedded Training Log db block
        rich = block.get(bt, {}).get("rich_text", [])
        text = "".join(r["plain_text"] for r in rich)

        if bt == "paragraph":
            lines.append(text)
        elif bt.startswith("heading_"):
            level = int(bt[-1])
            lines.append("#" * level + " " + text)
        elif bt == "bulleted_list_item":
            lines.append("- " + text)
        elif bt == "numbered_list_item":
            lines.append("1. " + text)
        elif bt == "code":
            lang = block.get("code", {}).get("language", "")
            code_text = "".join(r["plain_text"] for r in block.get("code", {}).get("rich_text", []))
            lines.append(f"```{lang}\n{code_text}\n```")
        elif bt == "divider":
            lines.append("---")
        else:
            if text:
                lines.append(text)

    return "\n".join(lines)


def _rich_text(text: str) -> list[dict]:
    """Parse a string with **bold** and *italic* into Notion rich_text objects."""
    import re
    parts = []
    pattern = re.compile(r'(\*\*(.+?)\*\*|\*(.+?)\*)')
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            parts.append({"type": "text", "text": {"content": text[pos:m.start()]}})
        if m.group(0).startswith("**"):
            parts.append({"type": "text", "text": {"content": m.group(2)},
                          "annotations": {"bold": True}})
        else:
            parts.append({"type": "text", "text": {"content": m.group(3)},
                          "annotations": {"italic": True}})
        pos = m.end()
    if pos < len(text):
        parts.append({"type": "text", "text": {"content": text[pos:]}})
    return parts or [{"type": "text", "text": {"content": text}}]


def _parse_table_row(line: str) -> list[str]:
    """Split a markdown table row into cell strings."""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def _is_table_separator(line: str) -> bool:
    return bool(line.strip()) and all(c in "-| :" for c in line.strip())


def _markdown_to_blocks(md: str) -> list[dict]:
    blocks = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect start of a markdown table (header row followed by separator)
        if (line.strip().startswith("|") and
                i + 1 < len(lines) and _is_table_separator(lines[i + 1])):
            header_cells = _parse_table_row(line)
            table_width = len(header_cells)
            rows = [header_cells]
            i += 2  # skip header + separator
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_parse_table_row(lines[i]))
                i += 1

            def cells_to_notion(cells):
                padded = (cells + [""] * table_width)[:table_width]
                return [_rich_text(c) for c in padded]

            table_block = {
                "object": "block",
                "type": "table",
                "table": {
                    "table_width": table_width,
                    "has_column_header": True,
                    "has_row_header": False,
                    "children": [
                        {"object": "block", "type": "table_row",
                         "table_row": {"cells": cells_to_notion(row)}}
                        for row in rows
                    ],
                },
            }
            blocks.append(table_block)
            continue

        if line.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                            "heading_3": {"rich_text": _rich_text(line[4:])}})
        elif line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                            "heading_2": {"rich_text": _rich_text(line[3:])}})
        elif line.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1",
                            "heading_1": {"rich_text": _rich_text(line[2:])}})
        elif line.startswith("- "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": _rich_text(line[2:])}})
        elif line == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            blocks.append({"object": "block", "type": "paragraph",
                            "paragraph": {"rich_text": _rich_text(line)}})
        i += 1
    return blocks


def update_plan(updated_plan: str) -> None:
    notion = _get_client()
    pid = _plan_page_id()

    existing = notion.blocks.children.list(block_id=pid)
    for block in existing["results"]:
        if block["type"] == "child_database":
            continue  # preserve the Training Log db
        notion.blocks.delete(block_id=block["id"])

    blocks = _markdown_to_blocks(updated_plan)
    for i in range(0, len(blocks), 100):
        notion.blocks.children.append(block_id=pid, children=blocks[i:i+100])


# ── Training Log database ─────────────────────────────────────────────────────

def get_training_log(days: int = 14) -> list[dict]:
    """Return Training Log rows for the past N days, most recent first."""
    notion = _get_client()
    since = (date.today() - timedelta(days=days)).isoformat()

    results = []
    cursor = None
    while True:
        kwargs = {
            "data_source_id": TRAINING_LOG_DS,
            "filter": {
                "property": "Date",
                "date": {"on_or_after": since}
            },
            "sorts": [{"property": "Date", "direction": "descending"}],
            "page_size": 100,
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.data_sources.query(**kwargs)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]

    rows = []
    for page in results:
        props = page["properties"]

        def text(key):
            v = props.get(key, {})
            rt = v.get("rich_text") or v.get("title") or []
            return "".join(r["plain_text"] for r in rt) if rt else None

        def num(key):
            v = props.get(key, {}).get("number")
            return v

        def sel(key):
            v = props.get(key, {}).get("select")
            return v["name"] if v else None

        def chk(key):
            return props.get(key, {}).get("checkbox", False)

        def dt(key):
            v = props.get(key, {}).get("date")
            return v["start"] if v else None

        rows.append({
            "page_id": page["id"],
            "date": dt("Date"),
            "session": text("Session"),
            "week": num("Week"),
            "phase": sel("Phase"),
            "day_type": sel("Day Type"),
            "planned_workout": text("Planned Workout"),
            "planned_miles": num("Planned Miles"),
            "completed": chk("Completed"),
            "actual_miles": num("Actual Miles"),
            "avg_hr": num("Avg HR"),
            "pace": text("Pace (min/mi)"),
            "hrv_status": sel("HRV Status"),
            "sleep_score": num("Sleep Score"),
            "body_battery": num("Body Battery"),
            "notes": text("Notes"),
        })
    return rows


def update_workout_row(page_id: str, **fields) -> None:
    """
    Update a single Training Log row. Pass any subset of:
      completed, actual_miles, avg_hr, pace, hrv_status,
      sleep_score, body_battery, notes
    """
    notion = _get_client()

    prop_map = {
        "completed": ("Completed", "checkbox"),
        "actual_miles": ("Actual Miles", "number"),
        "avg_hr": ("Avg HR", "number"),
        "pace": ("Pace (min/mi)", "rich_text"),
        "hrv_status": ("HRV Status", "select"),
        "sleep_score": ("Sleep Score", "number"),
        "body_battery": ("Body Battery", "number"),
        "notes": ("Notes", "rich_text"),
    }

    properties = {}
    for key, value in fields.items():
        if key not in prop_map or value is None:
            continue
        notion_name, notion_type = prop_map[key]
        if notion_type == "checkbox":
            properties[notion_name] = {"checkbox": bool(value)}
        elif notion_type == "number":
            properties[notion_name] = {"number": float(value)}
        elif notion_type == "rich_text":
            properties[notion_name] = {"rich_text": [{"text": {"content": str(value)}}]}
        elif notion_type == "select":
            properties[notion_name] = {"select": {"name": str(value)}}

    if properties:
        notion.pages.update(page_id=page_id, properties=properties)
