"""Parse a slice plan's Markdown file into an events JSON array.

This is the missing link in the export pipeline: the plan lives as a
human-readable `.md` (the single source of truth), but `export_html.py` /
`export_ics.py` consume a structured JSON. This script extracts the
per-day task cards (with the three-piece completion standard) from the
`.md` and emits that JSON — so the Markdown stays the only thing you edit.

Usage:
    python plan_to_events.py --in plan.md --out events.json [--name "My Goal"]

Output schema (one object per task card, matches export_html.py):
    {
      "date": "YYYY-MM-DD",
      "title": "...",
      "kind": "新内容 | 复习 | 缓冲 | 微任务 | 休息",   # inferred
      "duration": "1.0h" | "" ,                            # from [..] bracket
      "sub":    [...],   # 子目标
      "accept": [...],   # 验收
      "recite": [...]    # 口述自检
    }

Only the Python standard library is used.
"""
import argparse
import json
import re

# Card header: "### 2026-08-18 周二 · <title> [<duration>]"
_HEADER_RE = re.compile(
    r"^###\s+(\d{4}-\d{2}-\d{2})\s+周[一二三四五六日]\s*·\s*(.+?)\s*(?:\[([^\]]*)\])?\s*$"
)
# Section start inside a card: "- **子目标**（...）：" etc.
_SECTION_RE = re.compile(r"^\s*-\s*\*\*(子目标|验收|口述自检|状态)\*\*")
# Bullet inside a section; captures the [ ] / [x] marker so we keep checkbox state.
_BULLET_RE = re.compile(r"^\s*[-*]\s*(?:\[([ xX])\]\s*)?(.*)$")
# Status glyph on the "**状态**：⬜ → 🟡 → ✅" line.
_STATUS_GLYPH_RE = re.compile(r"[⬜🟡✅⏭]")

_KIND_KEYWORDS = [
    ("复习", "复习"),
    ("缓冲", "缓冲"),
    ("微任务", "微任务"),
    ("微", "微任务"),
    ("休息", "休息"),
]


def _infer_kind(title: str) -> str:
    for needle, kind in _KIND_KEYWORDS:
        if needle in title:
            return kind
    return "新内容"


def parse_plan(text: str):
    events = []
    current = None
    section = None

    def flush(ev):
        if ev is not None:
            events.append(ev)

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        m = _HEADER_RE.match(line)
        if m:
            flush(current)
            date, title, duration = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
            current = {
                "date": date,
                "title": title,
                "kind": _infer_kind(title),
                "duration": duration if duration and duration != "—" else "",
                "sub": [],
                "accept": [],
                "recite": [],
                "sub_done": [],
                "accept_done": [],
                "recite_done": [],
                "status": "",
            }
            section = None
            continue

        if current is None:
            continue

        s = _SECTION_RE.match(line)
        if s:
            section = s.group(1)
            if section == "状态":
                gm = _STATUS_GLYPH_RE.search(line)
                if gm:
                    current["status"] = gm.group(0)
            continue

        if section in ("子目标", "验收", "口述自检"):
            b = _BULLET_RE.match(line)
            if b:
                marker, item = b.group(1), b.group(2).strip()
                if item:
                    key = {"子目标": "sub", "验收": "accept", "口述自检": "recite"}[section]
                    current[key].append(item)
                    current[key + "_done"].append(marker in ("x", "X"))

    flush(current)
    return events


def main():
    ap = argparse.ArgumentParser(description="Slice plan .md -> events JSON")
    ap.add_argument("--in", dest="src", required=True, help="source plan .md")
    ap.add_argument("--out", dest="dst", required=True, help="output events .json")
    ap.add_argument("--name", default="", help="plan name (kept for compatibility)")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8") as f:
        text = f.read()

    events = parse_plan(text)
    with open(args.dst, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)

    print(f"parsed {len(events)} task cards -> {args.dst}")


if __name__ == "__main__":
    main()
