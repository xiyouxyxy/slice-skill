"""Export a slice plan's events JSON into a standalone HTML checklist.

Usage:
    python export_html.py --in events.json --out plan.html --name "My Goal"

The JSON is an array of events. Each event supports two schemas:

  Flat (legacy / ics-style):
    {"date": "YYYY-MM-DD", "title": "...", "desc": "..."}

  Three-piece (richer):
    {
      "date": "2026-08-07",
      "title": "M1: Python 语法回顾",
      "kind": "新内容",         # optional
      "duration": "1.0h",       # optional
      "sub": [...],              # 子目标 (optional)
      "accept": [...],           # 验收 (optional)
      "recite": [...]            # 口述自检 (optional)
    }

When the three-piece fields are present, the HTML renders them as nested
checkboxes so the user can tick off each piece individually. A task's
header checkbox auto-completes when every piece under it is checked.

Checkbox state is persisted in the browser's localStorage so ticks survive
closing / reopening the file. A plan-scoped key (derived from title + date
span) keeps state stable even if the file is renamed or moved. There is also
an export / import button as a portable backup (useful when file:// localStorage
is restricted by the browser).

Only the Python standard library is used. Output opens in any browser.
"""
import argparse
import html
import json
from datetime import datetime

_WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
_KIND_COLOR = {"新内容": "#2da44e", "复习": "#8250df", "缓冲": "#bf8700", "休息": "#8b949e"}


def _group(events):
    days = {}
    for ev in events:
        d = str(ev.get("date", "")).strip()
        if len(d) != 10 or d[4] != "-" or d[7] != "-":
            continue
        days.setdefault(d, []).append(ev)
    return dict(sorted(days.items()))


def _date_label(d: str) -> str:
    try:
        wk = _WEEKDAYS[datetime.strptime(d, "%Y-%m-%d").weekday()]
        return f"{d} 周{wk}"
    except Exception:
        return d


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _base_id(ev: dict, d: str) -> str:
    return f"{d}-{abs(hash(json.dumps(ev, ensure_ascii=False, sort_keys=True))) % 100000}"


def _piece(label: str, items, base_id: str) -> str:
    """Render a labeled nested checkbox group: 'label' with N items."""
    if not items:
        return ""
    lines = [f'<div class="piece"><div class="piece-label">{_esc(label)}</div><ul class="piece-list">']
    for i, it in enumerate(items):
        cid = f"{base_id}-{label}-{i}"
        lines.append(
            f"<li><input type='checkbox' class='ev-sub' id='{cid}'>"
            f"<label for='{cid}'>{_esc(it)}</label></li>"
        )
    lines.append("</ul></div>")
    return "\n".join(lines)


def _event_block(ev, base_id: str) -> str:
    """Render one event: title row + (optional) three nested pieces."""
    title = ev.get("title", "")
    kind = ev.get("kind", "")
    duration = ev.get("duration", "")
    desc = ev.get("desc", "")
    sub = ev.get("sub") or []
    accept = ev.get("accept") or []
    recite = ev.get("recite") or []

    badge_color = _KIND_COLOR.get(kind, "#656d76")
    badge = f'<span class="kind" style="background:{badge_color}">{_esc(kind)}</span>' if kind else ""
    dur = f'<span class="dur">{_esc(duration)}</span>' if duration else ""

    head = (
        f"<div class='ev-head'>"
        f"{badge}<input type='checkbox' class='ev-main' id='{base_id}'>"
        f"<label for='{base_id}' class='ev-title'>{_esc(title)}</label>{dur}"
        f"</div>"
    )
    body_parts = []
    if desc:
        body_parts.append(f'<div class="desc">{_esc(desc)}</div>')
    if sub or accept or recite:
        body_parts.append('<div class="pieces">')
        body_parts.append(_piece("子目标", sub, base_id))
        body_parts.append(_piece("验收", accept, base_id))
        body_parts.append(_piece("口述自检", recite, base_id))
        body_parts.append("</div>")
    return f"<div class='event'>{head}{''.join(body_parts)}</div>"


def _plan_key(events, title: str) -> str:
    """Stable, content-derived key so localStorage survives file rename/move."""
    dates = sorted(str(ev.get("date", "")) for ev in events if ev.get("date"))
    first = dates[0] if dates else ""
    last = dates[-1] if dates else ""
    return f"{title}|{len(events)}|{first}|{last}"


def build_html(events, title: str = "Slice Plan") -> str:
    days = _group(events)
    plan_key = _plan_key(events, title)
    css = """
body{font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;max-width:780px;margin:24px auto;padding:0 16px;color:#1f2328;line-height:1.55;}
h1{font-size:22px;margin-bottom:4px;}
.meta{color:#656d76;font-size:13px;margin-bottom:8px;}
.bar{position:sticky;top:0;background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:8px 12px;margin:6px 0 18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;box-shadow:0 1px 3px rgba(0,0,0,.06);}
#progress{font-weight:600;font-size:14px;}
.bar button{font:inherit;font-size:12px;padding:4px 10px;border:1px solid #d0d7de;border-radius:5px;background:#f6f8fa;cursor:pointer;}
.bar button:hover{background:#eaeef2;}
.day{margin:18px 0;padding:10px 12px;background:#f6f8fa;border-radius:6px;}
.date{font-weight:600;font-size:15px;border-left:3px solid #2da44e;padding-left:8px;margin-bottom:8px;}
.event{margin:8px 0;padding:6px 8px;border-radius:5px;}
.event.done{background:#eafbe7;border-left:3px solid #2da44e;}
.ev-head{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}
.ev-title{font-weight:500;cursor:pointer;}
.kind{font-size:11px;color:#fff;padding:2px 8px;border-radius:10px;}
.dur{color:#656d76;font-size:12px;margin-left:auto;}
.pieces{margin:6px 0 6px 22px;display:flex;flex-direction:column;gap:6px;}
.piece{background:#fff;border:1px solid #d0d7de;border-radius:4px;padding:6px 10px;}
.piece-label{font-size:12px;color:#57606a;font-weight:600;margin-bottom:4px;}
.piece-list{list-style:none;padding-left:0;margin:0;}
.piece-list li{margin:3px 0;font-size:13px;}
.piece-list input{margin-right:6px;}
input[type=checkbox]{transform:translateY(1px);}
.desc{color:#57606a;font-size:13px;margin-left:24px;}
footer{margin-top:30px;color:#8b949e;font-size:12px;border-top:1px solid #d0d7de;padding-top:10px;}
@media print{body{margin:0;} .noprint{display:none;} .day{break-inside:avoid;} .bar{position:static;}}
""".strip()
    p = []
    p.append("<!DOCTYPE html>")
    p.append('<html lang="zh-CN"><head><meta charset="utf-8">')
    p.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    p.append(f"<title>{_esc(title)} · 切片计划</title>")
    p.append(f"<style>{css}</style></head><body>")
    p.append(f"<h1>{_esc(title)} · 切片计划</h1>")
    p.append(
        f'<div class="meta">共 {len(days)} 天 · {len(events)} 个任务 · 生成于 '
        f'{datetime.now().strftime("%Y-%m-%d %H:%M")} · 由 slice skill 生成</div>'
    )
    p.append(
        '<div class="bar noprint">'
        '<span id="progress">已完成 0 / 0 任务</span>'
        '<button id="exportBtn" type="button">导出进度</button>'
        '<button id="importBtn" type="button">导入进度</button>'
        '<button id="resetBtn" type="button">重置</button>'
        '<input type="file" id="importFile" accept=".json" style="display:none">'
        "</div>"
    )
    if not days:
        p.append("<p>没有可导出的任务。</p>")
    for d, items in days.items():
        p.append(f'<div class="day"><div class="date">{_esc(_date_label(d))}</div>')
        for ev in items:
            p.append(_event_block(ev, _base_id(ev, d)))
        p.append("</div>")
    p.append('<footer class="noprint">勾选完成的任务会自动保存到本机浏览器（localStorage）。'
             'header 勾选框在该任务下所有子项都勾上后自动打勾；✅ 表示三件套（子目标/验收/口述）全过。'
             '按 Ctrl/Cmd+P 可打印。担心浏览器不保存时，用「导出进度」备份为 JSON。</footer>')
    p.append(_SCRIPT.replace("{{PLAN_KEY}}", _esc(plan_key)))
    p.append("</body></html>")
    return "\n".join(p)


_SCRIPT = """
<script>
(function(){
  var PLAN_KEY = 'slice-plan-state:{{PLAN_KEY}}';
  function load(){ try{ return JSON.parse(localStorage.getItem(PLAN_KEY)) || {}; }catch(e){ return {}; } }
  function save(map){ try{ localStorage.setItem(PLAN_KEY, JSON.stringify(map)); }catch(e){} }
  var state = load();

  var events = Array.prototype.slice.call(document.querySelectorAll('.event'));
  function subBoxesOf(ev){ return Array.prototype.slice.call(ev.querySelectorAll('input.ev-sub')); }
  function mainBoxOf(ev){ return ev.querySelector('input.ev-main'); }
  function syncMain(ev){
    var main = mainBoxOf(ev); if(!main) return;
    var subs = subBoxesOf(ev);
    if(subs.length){ main.checked = subs.every(function(b){ return b.checked; }); }
  }
  function refreshEvent(ev){
    syncMain(ev);
    var main = mainBoxOf(ev);
    ev.classList.toggle('done', !!main && main.checked);
  }
  function updateProgress(){
    var total = events.length, done = 0;
    events.forEach(function(ev){ var m = mainBoxOf(ev); if(m && m.checked) done++; });
    var p = document.getElementById('progress');
    if(p) p.textContent = '已完成任务 ' + done + ' / ' + total
      + '（' + (total ? Math.round(done/total*100) : 0) + '%）';
  }
  function applyState(){
    var all = document.querySelectorAll('input[type=checkbox]');
    all.forEach(function(b){ b.checked = !!state[b.id]; });
    events.forEach(refreshEvent);
    updateProgress();
  }
  applyState();

  document.querySelectorAll('input[type=checkbox]').forEach(function(b){
    b.addEventListener('change', function(){
      var ev = b.closest('.event');
      if(b.classList.contains('ev-main') && ev){
        subBoxesOf(ev).forEach(function(s){ s.checked = b.checked; if(b.checked){ state[s.id]=1; } else { delete state[s.id]; } });
      }
      if(b.checked){ state[b.id]=1; } else { delete state[b.id]; }
      save(state);
      if(ev) refreshEvent(ev);
      updateProgress();
    });
  });

  document.getElementById('exportBtn').addEventListener('click', function(){
    var data = { key: PLAN_KEY, state: state, exportedAt: new Date().toISOString() };
    var blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'slice-progress.json'; a.click();
    URL.revokeObjectURL(a.href);
  });
  var imp = document.getElementById('importFile');
  document.getElementById('importBtn').addEventListener('click', function(){ imp.click(); });
  imp.addEventListener('change', function(){
    var f = imp.files[0]; if(!f) return;
    var r = new FileReader();
    r.onload = function(){
      try{
        var data = JSON.parse(r.result);
        if(data && data.state){ state = data.state; save(state); applyState(); }
        else { alert('导入失败：未找到进度数据'); }
      }catch(e){ alert('导入失败：文件格式不正确'); }
    };
    r.readAsText(f);
    imp.value = '';
  });
  document.getElementById('resetBtn').addEventListener('click', function(){
    if(confirm('确定清空所有勾选状态？此操作不可撤销。')){ state = {}; save(state); applyState(); }
  });
})();
</script>
"""


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
    pieces = sum(1 for ev in events if ev.get("sub") or ev.get("accept") or ev.get("recite"))
    print(f"Wrote {len(events)} events ({pieces} with three-piece criteria) to {args.outfile}")


if __name__ == "__main__":
    main()
