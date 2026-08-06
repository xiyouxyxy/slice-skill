#!/usr/bin/env python3
"""Export a slice plan to an .ics calendar file (all-day events).

Usage:
    python export_ics.py --in events.json --out plan.ics [--name "Slice Plan"]

events.json format (UTF-8, array of objects):
    [
      {"date": "2026-08-07", "title": "M1-1 环境搭建", "desc": "安装 Python 与 Pandas"},
      {"date": "2026-08-08", "title": "M1-2 DataFrame 基础", "desc": ""}
    ]

Notes:
    - `date` must be YYYY-MM-DD; malformed rows are skipped.
    - Events are all-day (DTSTART;VALUE=DATE), which imports cleanly into
      Google / Apple / Outlook calendars as day-long tasks.
    - Commas and newlines in title/desc are escaped per RFC 5545.
"""
import argparse
import json
from datetime import datetime, timezone


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(events: list, cal_name: str = "Slice Plan"):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WorkBuddy//Slice//CN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(cal_name)}",
    ]
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    count = 0
    for i, ev in enumerate(events):
        date = str(ev.get("date", "")).replace("-", "")
        if len(date) != 8 or not date.isdigit():
            continue
        title = _escape(str(ev.get("title", "Task")))
        desc = _escape(str(ev.get("desc", "")))
        lines += [
            "BEGIN:VEVENT",
            f"UID:slice-{i}-{date}@workbuddy",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{date}",
            f"SUMMARY:{title}",
        ]
        if desc:
            lines.append(f"DESCRIPTION:{desc}")
        lines.append("END:VEVENT")
        count += 1
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n", count


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert a slice plan to .ics")
    ap.add_argument("--in", dest="infile", required=True, help="path to events JSON")
    ap.add_argument("--out", dest="outfile", default="plan.ics", help="output .ics path")
    ap.add_argument("--name", default="Slice Plan", help="calendar name")
    args = ap.parse_args()

    with open(args.infile, "r", encoding="utf-8") as f:
        events = json.load(f)

    ics, count = build_ics(events, args.name)
    with open(args.outfile, "w", encoding="utf-8", newline="") as f:
        f.write(ics)

    print(f"Wrote {count} events to {args.outfile}")


if __name__ == "__main__":
    main()
