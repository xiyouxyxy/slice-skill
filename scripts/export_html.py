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
      "sub": [...],             # 子目标 (optional)
      "accept": [...],          # 验收 (optional)
      "recite": [...],          # 口述自检 (optional)
      "sub_done": [...],        # 与 sub 对齐的勾选状态（来自 .md 的 - [x]）
      "accept_done": [...],     # 与 accept 对齐
      "recite_done": [...],     # 与 recite 对齐
      "status": "✅",           # 卡片状态行（⬜/🟡/✅/⏭），可选
      "review_src": [...]       # 复习卡"复习指向"——动态指回的原始任务/里程碑
    }

状态源统一（P2）设计要点
------------------------
- **`.md` 计划文件是唯一真源**。`.md` 里 `- [x]` 的勾选与 `**状态**` 行由
  `plan_to_events.py` 解析进 events JSON 的 `*_done` / `status` 字段，本脚本
  把它们**烘焙进 HTML 的默认勾选状态**。
- 浏览器 `localStorage` 只是离线工作副本：用户在本页勾选会写入它。
- 版本号机制：每次重新生成 HTML 会按 events 内容算一个 `plan_version` 并写入
  页面。打开页面时若发现 `localStorage` 里的版本与当前不符 → 说明 `.md` 已被
  改写（如 AI 打卡回写），**以 .md 烘焙的真值覆盖过期浏览器勾选**。版本相符
  时则沿用浏览器勾选（用户离线补勾的进度不丢）。
- 回写：本页「导出回写指令」按钮产出一份 JSON（按 date+title 定位卡片、列出
  各三件套勾选布尔 + 口述文字答案），交给 AI 即可写回 `.md`。

P3 增强
------
- 口述自检每项附一个**可编辑 textarea**，存用户自己的口述答案；内容持久化到
  localStorage（跨版本保留，因为答案属于用户而非 .md 真源），并在「导出回写指令」
  JSON 的 `recite_text` 中一同导出。
- 复习卡渲染 `review_src`（**复习指向**），动态指回它覆盖的原始任务/里程碑，
  而不是写死的泛化文案。

只有 Python 标准库被使用。输出文件任意浏览器可开。
"""
import argparse
import hashlib
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


def _piece(label: str, items, done, base_id: str, piece_key: str, texts=None) -> str:
    """Render a labeled nested checkbox group with .md-derived checked state.

    For the 口述自检 piece, each item also gets an editable textarea so the
    user can store their own oral answer (P3).
    """
    if not items:
        return ""
    if not done:
        done = []
    lines = [f'<div class="piece"><div class="piece-label">{_esc(label)}</div><ul class="piece-list">']
    for i, it in enumerate(items):
        cid = f"{base_id}-{piece_key}-{i}"
        checked = " checked" if (i < len(done) and done[i]) else ""
        text_html = ""
        if piece_key == "recite":
            tid = f"{cid}-text"
            val = _esc(texts[i]) if texts and i < len(texts) and texts[i] else ""
            text_html = (
                f"<textarea class='recite-text' id='{tid}' data-for='{cid}' "
                f"placeholder='在此写下你的口述答案（可选）'>{val}</textarea>"
            )
        lines.append(
            f"<li><input type='checkbox' class='ev-sub' id='{cid}' "
            f"data-piece='{piece_key}' data-idx='{i}'{checked}>"
            f"<label for='{cid}'>{_esc(it)}</label>{text_html}</li>"
        )
    lines.append("</ul></div>")
    return "\n".join(lines)


def _event_block(ev, base_id: str) -> str:
    """Render one event: title row + (optional) three nested pieces + review pointer."""
    title = ev.get("title", "")
    kind = ev.get("kind", "")
    duration = ev.get("duration", "")
    desc = ev.get("desc", "")
    sub = ev.get("sub") or []
    accept = ev.get("accept") or []
    recite = ev.get("recite") or []
    sub_done = ev.get("sub_done") or []
    accept_done = ev.get("accept_done") or []
    recite_done = ev.get("recite_done") or []
    recite_text = ev.get("recite_text") or []
    review_src = ev.get("review_src") or []
    date = ev.get("date", "")

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
        body_parts.append(_piece("子目标", sub, sub_done, base_id, "sub"))
        body_parts.append(_piece("验收", accept, accept_done, base_id, "accept"))
        body_parts.append(_piece("口述自检", recite, recite_done, base_id, "recite", recite_text))
        body_parts.append("</div>")
    if review_src:
        body_parts.append(
            f'<div class="review-src">复习指向：{" / ".join(_esc(x) for x in review_src)}</div>'
        )
    return (
        f"<div class='event' data-date='{_esc(date)}' data-title='{_esc(title)}'>"
        f"{head}{''.join(body_parts)}</div>"
    )


def _plan_key(events, title: str) -> str:
    """Stable, content-derived key so localStorage survives file rename/move."""
    dates = sorted(str(ev.get("date", "")) for ev in events if ev.get("date"))
    first = dates[0] if dates else ""
    last = dates[-1] if dates else ""
    return f"{title}|{len(events)}|{first}|{last}"


def _plan_version(events) -> str:
    """Hash of the events content — changes whenever the .md (source) changes."""
    payload = json.dumps(events, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_html(events, title: str = "Slice Plan") -> str:
    days = _group(events)
    plan_key = _plan_key(events, title)
    plan_version = _plan_version(events)
    meta_list = [
        {
            "date": ev.get("date", ""),
            "title": ev.get("title", ""),
            "sub_n": len(ev.get("sub") or []),
            "accept_n": len(ev.get("accept") or []),
            "recite_n": len(ev.get("recite") or []),
        }
        for ev in events
    ]
    css = """
body{font-family:-apple-system,'Segoe UI',Roboto,'Microsoft YaHei',sans-serif;max-width:780px;margin:24px auto;padding:0 16px;color:#1f2328;line-height:1.55;}
h1{font-size:22px;margin-bottom:4px;}
.meta{color:#656d76;font-size:13px;margin-bottom:8px;}
.banner{background:#fff8e6;border:1px solid #f0d58c;border-left:3px solid #bf8700;color:#7a5b00;
  font-size:12.5px;padding:7px 11px;border-radius:5px;margin:6px 0 10px;}
.banner code{background:#f3e9cf;padding:1px 5px;border-radius:3px;}
.bar{position:sticky;top:0;background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:8px 12px;margin:6px 0 18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;box-shadow:0 1px 3px rgba(0,0,0,.06);}
#progress{font-weight:600;font-size:14px;}
.bar button{font:inherit;font-size:12px;padding:4px 10px;border:1px solid #d0d7de;border-radius:5px;background:#f6f8fa;cursor:pointer;}
.bar button:hover{background:#eaeef2;}
#srcNote{color:#8250df;font-size:12px;}
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
.recite-text{display:block;width:96%;margin:4px 0 6px 26px;font:inherit;font-size:12.5px;padding:5px 7px;
  border:1px solid #d0d7de;border-radius:4px;box-sizing:border-box;resize:vertical;min-height:34px;color:#1f2328;}
.recite-text:focus{outline:none;border-color:#8250df;}
.review-src{margin:6px 0 6px 22px;font-size:12.5px;color:#8250df;background:#faf5ff;border-left:3px solid #8250df;
  padding:5px 9px;border-radius:4px;}
.desc{color:#57606a;font-size:13px;margin-left:24px;}
footer{margin-top:30px;color:#8b949e;font-size:12px;border-top:1px solid #d0d7de;padding-top:10px;}
@media print{body{margin:0;} .noprint{display:none;} .day{break-inside:avoid;} .bar{position:static;}
  .recite-text{display:none;} .review-src{background:none;border-color:#8250df;}}
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
        '<div class="banner noprint">本页勾选仅存于本机浏览器；<b>唯一真源是 '
        '<code>.md</code> 计划文件</b>。想让进度正式生效，用「导出回写指令」交给 AI 写回 .md。'
        '口述自检框下的文本框可随手记下自己的口述答案，仅保存在本机。</div>'
    )
    p.append(
        '<div class="bar noprint">'
        '<span id="progress">已完成 0 / 0 任务</span>'
        '<button id="flushBtn" type="button">导出回写指令</button>'
        '<button id="exportBtn" type="button">导出进度</button>'
        '<button id="importBtn" type="button">导入进度</button>'
        '<button id="resetBtn" type="button">重置</button>'
        '<span id="srcNote"></span>'
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
    p.append('<footer class="noprint">唯一真源是 <code>.md</code> 计划文件；本页勾选是离线副本。'
             'header 勾选框在该任务下所有子项都勾上后自动打勾；✅ 表示三件套（子目标/验收/口述）全过。'
             '口述自检下方的文本框可记录你的口述答案（仅本机保存）。'
             '按 Ctrl/Cmd+P 可打印。担心浏览器不保存时，用「导出进度」备份为 JSON；'
             '想让进度生效，用「导出回写指令」交给 AI 写回 .md。</footer>')
    p.append(f"<script>window.__SLICE_EVENTS__ = {json.dumps(meta_list, ensure_ascii=False)};</script>")
    p.append(
        _SCRIPT.replace("{{PLAN_KEY}}", _esc(plan_key))
        .replace("{{PLAN_VERSION}}", _esc(plan_version))
        .replace("{{PLAN_TITLE}}", _esc(title))
    )
    p.append("</body></html>")
    return "\n".join(p)


_SCRIPT = """
<script>
(function(){
  var PLAN_KEY = 'slice-plan-state:{{PLAN_KEY}}';
  var PLAN_VERSION = '{{PLAN_VERSION}}';
  var PLAN_TITLE = '{{PLAN_TITLE}}';
  var VER_KEY = PLAN_KEY + ':v';
  var TEXT_PREFIX = PLAN_KEY + ':text:';
  function loadState(){ try{ return JSON.parse(localStorage.getItem(PLAN_KEY)) || {}; }catch(e){ return {}; } }
  function saveState(s){ try{ localStorage.setItem(PLAN_KEY, JSON.stringify(s)); localStorage.setItem(VER_KEY, PLAN_VERSION); }catch(e){} }
  function loadText(id){ try{ return localStorage.getItem(TEXT_PREFIX + id) || ''; }catch(e){ return ''; } }
  function saveText(id, val){ try{ if(val){ localStorage.setItem(TEXT_PREFIX + id, val); } else { localStorage.removeItem(TEXT_PREFIX + id); } }catch(e){} }
  var storedVersion = (function(){ try{ return localStorage.getItem(VER_KEY); }catch(e){ return null; } })();
  var useStored = (storedVersion === PLAN_VERSION);
  var state = useStored ? loadState() : {};

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
    document.querySelectorAll('input[type=checkbox]').forEach(function(b){ b.checked = !!state[b.id]; });
    events.forEach(refreshEvent);
    updateProgress();
  }
  // 还原口述文本框（用户自己的答案，独立于勾选状态，跨版本保留）
  function restoreTexts(){
    document.querySelectorAll('textarea.recite-text').forEach(function(t){ t.value = loadText(t.id); });
  }

  if(useStored){
    // 版本相符：沿用浏览器离线勾选（用户补勾的进度不丢）
    applyState();
  } else {
    // 版本不符：.md 已被改写，以 HTML 里烘焙的 .md 真值为准，丢弃过期浏览器勾选
    state = {};
    document.querySelectorAll('input[type=checkbox]').forEach(function(b){ if(b.checked) state[b.id]=1; });
    if(storedVersion !== null){
      var n = document.getElementById('srcNote');
      if(n) n.textContent = '已用 .md 最新状态覆盖旧浏览器勾选';
    }
    saveState(state);
  }
  restoreTexts();

  document.querySelectorAll('input[type=checkbox]').forEach(function(b){
    b.addEventListener('change', function(){
      var ev = b.closest('.event');
      if(b.classList.contains('ev-main') && ev){
        subBoxesOf(ev).forEach(function(s){ s.checked = b.checked; if(b.checked){ state[s.id]=1; } else { delete state[s.id]; } });
      }
      if(b.checked){ state[b.id]=1; } else { delete state[b.id]; }
      saveState(state);
      if(ev) refreshEvent(ev);
      updateProgress();
    });
  });
  document.querySelectorAll('textarea.recite-text').forEach(function(t){
    t.addEventListener('input', function(){ saveText(t.id, t.value); });
  });

  // 导出进度（localStorage 便携备份，含勾选 + 口述文字）
  function collectTexts(){
    var m = {};
    document.querySelectorAll('textarea.recite-text').forEach(function(t){ if(t.value) m[t.id] = t.value; });
    return m;
  }
  document.getElementById('exportBtn').addEventListener('click', function(){
    var data = { key: PLAN_KEY, version: PLAN_VERSION, state: state, texts: collectTexts(), exportedAt: new Date().toISOString() };
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
        if(data && data.state){
          state = data.state;
          if(data.texts){ for(var k in data.texts){ saveText(k, data.texts[k]); } }
          saveState(state); applyState(); restoreTexts();
        } else { alert('导入失败：未找到进度数据'); }
      }catch(e){ alert('导入失败：文件格式不正确'); }
    };
    r.readAsText(f);
    imp.value = '';
  });
  document.getElementById('resetBtn').addEventListener('click', function(){
    if(confirm('确定清空所有勾选状态与口述文本？此操作不可撤销。')){
      state = {}; saveState(state); applyState();
      document.querySelectorAll('textarea.recite-text').forEach(function(t){ t.value=''; saveText(t.id,''); });
    }
  });

  // 导出回写指令：产出可交给 AI 写回 .md 的 JSON（按 date+title 定位卡片）
  document.getElementById('flushBtn').addEventListener('click', function(){
    var meta = window.__SLICE_EVENTS__ || [];
    var cards = events.map(function(ev, idx){
      var m = meta[idx] || {date:'', title:''};
      var sub=[], accept=[], recite=[], recite_text=[];
      ev.querySelectorAll('input.ev-sub').forEach(function(b){
        var p = b.getAttribute('data-piece');
        if(p==='sub') sub.push(b.checked);
        else if(p==='accept') accept.push(b.checked);
        else if(p==='recite') recite.push(b.checked);
      });
      ev.querySelectorAll('textarea.recite-text').forEach(function(t){ recite_text.push(t.value); });
      return {date: m.date, title: m.title, sub: sub, accept: accept, recite: recite, recite_text: recite_text};
    });
    var data = { slice_flush: 1, title: PLAN_TITLE, version: PLAN_VERSION, cards: cards };
    var blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'slice-flush.json'; a.click();
    URL.revokeObjectURL(a.href);
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
