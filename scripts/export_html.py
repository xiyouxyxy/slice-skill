"""Export a slice plan's events JSON into a standalone HTML checklist.

Usage:
    python export_html.py --in events.json --out plan.html --name "My Goal"

The JSON is an array of {"date": "YYYY-MM-DD", "title": "...", "desc": "..."}.
Only the Python standard library is used, so no `pip install` is required.
The output HTML opens in any browser by double-clicking — no extra software needed.
"""
import argparse
import html
import json
from datetime import datetime

_WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


def _group(events):
    days = {}
    for ev in events:
        date = str(ev.get("date", "")).strip()
        if len(date) != 10 or date[4] != "-" or date[7] != "-":
            continue
        days.setdefault(date, []).append(ev)
    return dict(sorted(days.items()))


def _date_label(date: str) -> str:
    try:
        wk = _WEEKDAYS[datetime.strptime(date, "%Y-%m-%d").weekday()]
        return f"{date} 周{wk}"
    except Exception:
        return date


def build_html(events, title: str = "Slice Plan") -> str:
    days = _group(events)
    p = []
    p.append("<!DOCTYPE html>")
    p.append('<html lang="zh-CN"><head><meta charset="utf-8">')
    p.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    p.append(f"<title>{html.escape(title)} · 切片计划</title>")
    p.append("<style>")
    p.append("body{font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#1f2328;line-height:1.6;}")
    p.append("h1{font-size:22px;margin-bottom:4px;}")
    p.append(".meta{color:#656d76;font-size:13px;margin-bottom:20px;}")
    p.append(".day{margin:18px 0;}")
    p.append(".date{font-weight:600;font-size:15px;border-left:3px solid #2da44e;padding-left:8px;}")
    p.append("ul{list-style:none;padding-left:14px;margin:8px 0;}")
    p.append("li{margin:6px 0;}")
    p.append("input{margin-right:8px;transform:translateY(1px);}")
    p.append(".desc{color:#57606a;font-size:13px;margin-left:4px;}")
    p.append("footer{margin-top:30px;color:#8b949e;font-size:12px;border-top:1px solid #d0d7de;padding-top:10px;}")
    p.append("@media print{body{margin:0;} .noprint{display:none;}}")
    p.append("</style></head><body>")
    p.append(f"<h1>{html.escape(title)} · 切片计划</h1>")
    p.append(
        f'<div class="meta">共 {len(days)} 天 · 生成于 '
        f'{datetime.now().strftime("%Y-%m-%d %H:%M")} · 由 WorkBuddy slice skill 生成</div>'
    )
    if not days:
        p.append("<p>没有可导出的任务。</p>")
    for date, items in days.items():
        p.append(f'<div class="day"><div class="date">{html.escape(_date_label(date))}</div><ul>')
        for ev in items:
            t = html.escape(str(ev.get("title", "")))
            d = html.escape(str(ev.get("desc", "")))
            desc = f'<span class="desc">{d}</span>' if d else ""
            p.append(
                f"<li><input type='checkbox' id='{date}-{t}'>"
                f"<label for='{date}-{t}'>{t}{desc}</label></li>"
            )
        p.append("</ul></div>")
    p.append('<footer class="noprint">勾选完成的任务，按 Ctrl/Cmd+P 即可打印为纸质清单。</footer>')
    p.append("</body></html>")
    return "\n".join(p)


def main():
    ap = argparse.ArgumentParser(description="Slice plan JSON -> standalone HTML checklist")
    ap.add_argument("--in", dest="infile", required=True, help="events JSON file")
    ap.add_argument("--out", dest="outfile", required=True, help="output .html file")
    ap.add_argument("--name", default="Slice Plan", help="plan title shown in the page")
    args = ap.parse_args()

    with open(args.infile, encoding="utf-8") as f:
        events = json.load(f)
    if not isinstance(events, list):
        events = []

    doc = build_html(events, args.name)
    with open(args.outfile, "w", encoding="utf-8", newline="") as f:
        f.write(doc)
    print(f"Wrote {len(events)} events to {args.outfile}")


if __name__ == "__main__":
    main()
