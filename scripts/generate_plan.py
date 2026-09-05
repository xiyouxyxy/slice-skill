#!/usr/bin/env python3
"""Slice 规划引擎：把 LLM 做完 WBS 后的结构化 spec 渲染成计划 .md。

这是 slice skill 文档（SKILL.md 步骤 3/4/5/6/7）里**确定性部分**的代码实现：
- WBS（定里程碑 / 任务 / 三件套）仍是 LLM 的语义活，输入本脚本的 spec；
- 本脚本负责**排程 + 渲染**：日期分配、每 5 个新任务插缓冲、里程碑 +1 复习、
  全局 +3/+7 间隔复习、可用日过滤，最后按 `references/plan-template.md` 输出 .md。

输入 spec JSON 结构（由 LLM 按 WBS 产出）：
{
  "meta": {
    "title": "三个月学会用 Python 做数据分析",
    "type": "学习",                       # 学习 / 项目 / 习惯
    "base": "入门",                       # 零基础 / 入门 / 有基础 / 进阶
    "complete_def": "能独立完成…",         # 完成定义（写进交付卡）
    "daily_duration": 1.0,                # 小时，可省默认 1.0
    "target_date": "2026-12-31",          # 可选；给定走"有截止日"分支
    "available_days": "weekdays+weekend"  # 或 "weekdays"
  },
  "prerequisites": {                      # 可选
    "tools": [...], "accounts": [...], "data": [...], "admin": [...],
    "status": "全部到位"                    # 或 "还缺：…"
  },
  "milestones": [
    {
      "name": "M1: Python 基础",
      "tasks": [
        {"title":"变量·类型·控制流","kind":"新内容","duration":1.0,
         "sub":[...],"accept":[...],"recite":[...]},
        ...
      ]
    },
    ...
  ]
}

用法：
  # 生成计划 .md
  python generate_plan.py build --in spec.json --out plan.md [--start 2026-09-05]

  # 落后自动重排（Step 9.2）：读已有计划，把未完成的过期任务顺延
  python generate_plan.py reschedule --in plan.md --today 2026-09-20 \
      --done 2026-09-05,2026-09-06 --out plan-rescheduled.md

仅依赖 Python 标准库。
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

# 让 reschedule 模式能复用 plan_to_events 的解析器
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from plan_to_events import parse_plan  # noqa: E402
except Exception:  # pragma: no cover
    parse_plan = None

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
KIND_LABEL = {"新内容": "新内容", "复习": "复习", "缓冲": "缓冲", "微任务": "微任务", "休息": "休息"}

# 全局间隔复习的轮次标签（每 2 个里程碑插一次，覆盖此前全部里程碑）
_GLOBAL_REVIEW_INTERVALS = [3, 7, 14, 30, 60]


def _cn_weekday(d: date) -> str:
    return WEEKDAY_CN[d.weekday()]


def _is_available(d: date, available_days: str) -> bool:
    if available_days == "weekdays":
        return d.weekday() < 5  # 跳过周六(5)/周日(6)
    return True  # weekdays+weekend（默认）


def _next_available(start: date, available_days: str) -> date:
    d = start
    while not _is_available(d, available_days):
        d += timedelta(days=1)
    return d


def _fmt_duration(hours) -> str:
    if hours is None:
        return "—"
    s = str(hours).strip().lower().rstrip("h").strip()
    try:
        h = float(s)
    except (TypeError, ValueError):
        return "—"
    if h <= 0:
        return "—"
    return f"{h:g}h"


# ---------------------------------------------------------------------------
# 1. 把 spec 展开成有序的"日程项"列表（含自动生成的复习/缓冲）
# ---------------------------------------------------------------------------
def build_items(spec: dict) -> list:
    """返回有序 item 列表：每个 item 是带渲染所需字段的 dict。"""
    milestones = spec.get("milestones", [])
    items = []
    new_since_buffer = 0
    global_review_idx = 0

    for mi, m in enumerate(milestones):
        mname = m.get("name", f"M{mi + 1}")
        tasks = m.get("tasks", [])
        for ti, t in enumerate(tasks):
            kind = t.get("kind", "新内容") or "新内容"
            items.append({
                "kind": kind,
                "title": f"{mname}: {t.get('title', f'任务{ti + 1}')}",
                "duration": t.get("duration"),
                "sub": t.get("sub", []),
                "accept": t.get("accept", []),
                "recite": t.get("recite", []),
                "milestone": mname,
                "milestone_idx": mi,
            })
            # 计数新内容/工作类任务，满 5 插一个缓冲日（Step 6）
            if kind in ("新内容", "微任务"):
                new_since_buffer += 1
            if new_since_buffer >= 5:
                items.append(_buffer_item())
                new_since_buffer = 0

        # 里程碑末 +1 复习（覆盖本里程碑）
        items.append(_milestone_review(mname, mi, tasks))

        # 每 2 个里程碑插一次全局间隔复习（+3 / +7 / …）
        if (mi + 1) % 2 == 0 and global_review_idx < len(_GLOBAL_REVIEW_INTERVALS):
            span = _GLOBAL_REVIEW_INTERVALS[global_review_idx]
            global_review_idx += 1
            items.append(_global_review(mi, span, milestones))

    return items


def _buffer_item() -> dict:
    return {
        "kind": "缓冲",
        "title": "缓冲日",
        "duration": None,
        "sub": ["不强求，做完三件套之一即可"],
        "accept": ["任选之前学过的 1 个子目标重新讲一遍 / 重做 1 道题"],
        "recite": ["任意 1 个旧难点的口述"],
        "milestone": "",
        "milestone_idx": -1,
    }


def _milestone_review(mname: str, mi: int, tasks: list) -> dict:
    # 从本里程碑任务里挑验收题，自动生成复习卡（无需 LLM 额外输入）
    accepts = []
    for t in tasks:
        for a in t.get("accept", [])[:2]:
            accepts.append(a)
    accepts = accepts[:3]
    recite_src = []
    for t in tasks:
        recite_src += t.get("recite", [])[:1]
    recite = recite_src[:2] if recite_src else [f"口述『{mname} 中最易混的 1 个点』"]
    return {
        "kind": "复习",
        "title": f"复习 {mname} 全部（+1 间隔复习）",
        "duration": 0.5,
        "sub": [f"能不看资料口述 {mname} 的核心点"],
        "accept": [f"重做关键验收题（{(' / '.join(accepts)) if accepts else '本里程碑重点题'}），能跑通"]
                  if accepts else ["重做本里程碑关键验收题，能跑通"],
        "recite": recite,
        "milestone": mname,
        "milestone_idx": mi,
    }


def _global_review(upto_idx: int, span: int, milestones: list) -> dict:
    covered = [m.get("name", f"M{i + 1}") for i, m in enumerate(milestones[:upto_idx + 1])]
    return {
        "kind": "复习",
        "title": f"全局复习（+{span} 间隔，覆盖 {' / '.join(covered)}）",
        "duration": 0.5,
        "sub": [f"能串联 {(' / '.join(covered))} 的主线"],
        "accept": ["重做此前任意 2 道验收题，能跑通"],
        "recite": [f"口述『{covered[-1]} 与 {covered[0]} 的关系』"],
        "milestone": "",
        "milestone_idx": -1,
    }


# ---------------------------------------------------------------------------
# 2. 排程：把有序 item 分配到可用日（Step 5）
# ---------------------------------------------------------------------------
def schedule(items: list, start: date, available_days: str, target_date=None):
    """返回带 date 字段的 item 列表。

    - 默认：1 个 item / 可用日（符合默认节奏"每天 1 原子任务"）。
    - 有 target_date 且可用日不足：在可用日里尽量均摊，单日可合并多项并标记 overload。
    """
    sched = []
    d = _next_available(start, available_days)
    overload = False

    if target_date:
        tgt = datetime.strptime(target_date, "%Y-%m-%d").date()
        # 统计 start..target 之间的可用日数量
        avail_count = 0
        cur = d
        while cur <= tgt:
            if _is_available(cur, available_days):
                avail_count += 1
            cur += timedelta(days=1)
        if avail_count < len(items):
            overload = True
            # 合并模式：把 items 均摊到 avail_count 天
            per_day = max(1, (len(items) + avail_count - 1) // max(avail_count, 1))
            i = 0
            while i < len(items):
                batch = items[i:i + per_day]
                titles = []
                for it in batch:
                    sched.append(dict(it, date=d))
                    titles.append(it["title"])
                if len(batch) > 1:
                    sched[-1]["_merged"] = True
                    sched[-1]["_merged_titles"] = titles
                d = _advance(d, available_days)
                i += per_day
            return sched, overload

    # 常规：1 item / 可用日
    for it in items:
        sched.append(dict(it, date=d))
        d = _advance(d, available_days)
    return sched, overload


def _advance(d: date, available_days: str) -> date:
    nxt = d + timedelta(days=1)
    return _next_available(nxt, available_days)


# ---------------------------------------------------------------------------
# 3. 渲染 .md（严格对齐 references/plan-template.md）
# ---------------------------------------------------------------------------
def render_md(spec: dict, sched: list, overload: bool) -> str:
    meta = spec.get("meta", {})
    title = meta.get("title", "未命名计划")
    gtype = meta.get("type", "学习")
    daily = meta.get("daily_duration", 1.0) or 1.0
    target = meta.get("target_date", "")
    avail = meta.get("available_days", "weekdays+weekend")
    base = meta.get("base", "")
    cdef = meta.get("complete_def", "")
    start = sched[0]["date"] if sched else date.today()
    finish = sched[-1]["date"] if sched else start

    total_h = sum((float(it["duration"]) for it in sched if it.get("duration")))
    total_tasks = sum(1 for it in sched if it["kind"] in ("新内容", "微任务"))

    L = []
    L.append(f"# {title}")
    L.append("")
    L.append("## 元信息")
    L.append("")
    L.append(f"- 目标：{title}")
    L.append(f"- 类型：{gtype}")
    if target:
        L.append(f"- 截止日：{target}")
    else:
        L.append("- 截止日：默认节奏，无固定截止日")
    L.append(f"- 每日时长预算：{_fmt_duration(daily)}（未设则默认节奏）")
    L.append(f"- 可用日：{'仅工作日' if avail == 'weekdays' else '周一至周五 + 周末'}")
    L.append(f"- 总工时估算：~{total_h:g}h（含验收时间）")
    L.append(f"- 预计完成日：{finish.isoformat()}")
    L.append("")

    # 用户画像（习惯型省略）
    if gtype != "习惯":
        L.append("## 用户画像（规划前访谈产出）")
        L.append("")
        L.append("> 步骤 0.2 用户访谈的产出。项目·学习必填；习惯型无此节。WBS 与重排都回看它。")
        L.append("")
        L.append(f"- 基础水平：{base or '未填'}")
        L.append(f"- 完成定义：{cdef or '未填'}")
        L.append(f"- 每日时长：{_fmt_duration(daily)}")
        L.append(f"- 期望完成日期：{target or '未设，默认节奏'}")
        L.append("")

    # 前置条件
    pre = spec.get("prerequisites")
    L.append("## 前置条件（动手前要备齐）")
    L.append("")
    L.append("> 步骤 0.1 入口问询的产出。项目型必填；学习/习惯型可留空，由 LLM 在里程碑头部按需补 `前置：…`。")
    L.append("")
    if pre:
        L.append(f"- 工具 / 软件：{('、'.join(pre.get('tools', [])) or '—')}")
        L.append(f"- 账号 / 权限：{('、'.join(pre.get('accounts', [])) or '—')}")
        L.append(f"- 数据 / 素材：{('、'.join(pre.get('data', [])) or '—')}")
        L.append(f"- 行政 / 治理：{('、'.join(pre.get('admin', [])) or '—')}")
        L.append(f"- 状态：{'☑ 全部到位（开始排程）' if pre.get('status') == '全部到位' else ('☐ 还缺：' + (pre.get('status', '') or '—'))}")
    else:
        L.append("- （未填写——LLM 在排里程碑时按需补 `前置：…`）")
    L.append("")

    # 总览
    L.append("## 总览")
    L.append("")
    for mi, m in enumerate(spec.get("milestones", [])):
        L.append(f"- 里程碑 {mi + 1}（M{mi + 1}）：{m.get('name', '')}")
    L.append("")

    # 每日计划概览表
    L.append("## 每日计划（高层概览）")
    L.append("")
    L.append("> 概览表只列日期 / 类型 / 任务标题 / 时长 / 状态，**详情见下方任务卡片**。")
    L.append("")
    L.append("| 日期 | 星期 | 类型 | 任务 | 时长 | 状态 |")
    L.append("|------|------|------|------|------|------|")
    for it in sched:
        dur = _fmt_duration(it.get("duration")) if not it.get("_merged") else "合并"
        title_cell = it["title"]
        if it.get("_merged"):
            title_cell = "；".join(it.get("_merged_titles", [it["title"]]))
        L.append(f"| {it['date'].isoformat()} | {_cn_weekday(it['date'])} | {it['kind']} | {title_cell} | {dur} | ⬜ |")
    L.append("")
    L.append("> 类型枚举：新内容 / 复习 / 缓冲 / 微任务。")
    L.append("> 复习任务在标题里附 `(+N)` 表示间隔复习轮次（+1 / +3 / +7）。")
    L.append("> 状态：`⬜` 待做 / `🟡` 部分（三件套未全勾）/ `✅` 全过（三件套全勾）/ `⏭` 跳过。")
    L.append("")

    if overload:
        L.append("> ⚠️ **时间紧**：可用日不足以 1 任务/天摊开，已合并部分日期。建议延长截止日或提高每日投入。")
        L.append("")

    # 任务卡片
    L.append("## 任务卡片（详情：完成标准三件套）")
    L.append("")
    L.append("> 每个原子任务一张卡片。**✅ 必须三件套全勾才算「完成」**，缺任一件套都只算 `🟡`。")
    L.append("")
    for it in sched:
        L.append(_render_card(it))
        L.append("")

    # 进度
    L.append("## 进度")
    L.append("")
    L.append(f"- 已完成：0 / {len(sched)} 天")
    L.append("- 三件套全过（✅）数：0")
    L.append("- 部分完成（🟡）数：0")
    L.append("- 连续打卡：0 天")
    L.append("- 最近一次重排：无")
    L.append("- 备注：")
    return "\n".join(L)


def _render_card(it: dict) -> str:
    d = it["date"]
    title = it["title"]
    if it.get("_merged"):
        title = "；".join(it.get("_merged_titles", [title]))
    dur = _fmt_duration(it.get("duration"))
    head = f"### {d.isoformat()} 周{_cn_weekday(d)} · {title} [{dur}]"
    lines = [head, ""]
    lines.append("- **子目标**（今天要会什么）：")
    for s in it.get("sub", []) or ["（无）"]:
        lines.append(f"  - [ ] {s}")
    lines.append("- **验收**（做完就勾）：")
    accepts = it.get("accept", []) or ["（无）"]
    for a in accepts:
        lines.append(f"  - [ ] {a}")
    lines.append("- **口述自检**（不查资料，能讲清就勾）：")
    for r in it.get("recite", []) or ["（无）"]:
        lines.append(f"  - [ ] {r}")
    lines.append("- **状态**：⬜ → 🟡 → ✅（全勾后改 ✅）")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# reschedule（Step 9.2 落后自动重排）
# ---------------------------------------------------------------------------
def reschedule(events: list, today: date, done_dates: set, available_days: str):
    """已完成（date<=today 且 in done）保留原位；其余项从 today 起顺延到可用空日。"""
    kept = [e for e in events if _date_of(e) and _date_of(e) <= today and _date_of(e).isoformat() in done_dates]
    rest = [e for e in events if not (_date_of(e) and _date_of(e) <= today and _date_of(e).isoformat() in done_dates)]
    out = list(kept)
    d = _next_available(today, available_days)
    for e in rest:
        e = dict(e)
        e["date"] = d.isoformat()
        out.append(e)
        d = _advance(d, available_days)
    return out


def _date_of(e) -> date:
    s = str(e.get("date", ""))
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_build(args):
    spec = _load_spec(args.spec)
    meta = spec.get("meta", {})
    start_str = args.start or meta.get("start") or date.today().isoformat()
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    avail = meta.get("available_days", "weekdays+weekend")

    items = build_items(spec)
    sched, overload = schedule(items, start, avail, meta.get("target_date"))
    md = render_md(spec, sched, overload)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)

    finish = sched[-1]["date"].isoformat() if sched else start_str
    note = " ⚠️时间紧(已合并日期)" if overload else ""
    print(f"生成计划：{args.out}")
    print(f"  任务项 {len(sched)} 个，预计完成日 {finish}{note}")


def cmd_reschedule(args):
    if parse_plan is None:
        print("错误：无法加载 plan_to_events.parse_plan", file=sys.stderr)
        return 1
    text = open(args.src, encoding="utf-8").read()
    events = parse_plan(text)
    today = datetime.strptime(args.today, "%Y-%m-%d").date()
    done = set(x.strip() for x in (args.done or "").split(",") if x.strip())
    avail = args.available_days
    new_events = reschedule(events, today, done, avail)
    # 直接复用 render 思路：转为轻量 md
    md = _render_rescheduled_md(new_events, args.today)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"重排完成：{args.out}（保留了 {len(done)} 个已完成日，顺延 {len(new_events) - len(done)} 项）")
    return 0


def _render_rescheduled_md(events: list, today: str) -> str:
    L = [f"# 重排后的计划（基于 {today}）", ""]
    L.append("> 落后自动重排（Step 9.2）产出：已完成日保留原位，其余项从今天起顺延到最近可用日。")
    L.append("")
    L.append("## 每日计划（高层概览）")
    L.append("")
    L.append("| 日期 | 星期 | 类型 | 任务 | 时长 | 状态 |")
    L.append("|------|------|------|------|------|------|")
    for e in events:
        d = _date_of(e)
        wk = _cn_weekday(d) if d else "?"
        dur = e.get("duration") or ""
        L.append(f"| {e.get('date','')} | {wk} | {e.get('kind','')} | {e.get('title','')} | {dur} | ⬜ |")
    L.append("")
    L.append("## 任务卡片（详情：完成标准三件套）")
    L.append("")
    for e in events:
        d = _date_of(e)
        it = dict(e, date=d or today)
        L.append(_render_card(it))
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Slice 规划引擎：spec -> 计划 .md")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", help="从 spec JSON 生成计划 .md")
    b.add_argument("--in", dest="spec", required=True, help="spec JSON 路径")
    b.add_argument("--out", dest="out", required=True, help="输出 .md 路径")
    b.add_argument("--start", default="", help="起始日 YYYY-MM-DD（默认今天）")

    r = sub.add_parser("reschedule", help="落后自动重排（Step 9.2）")
    r.add_argument("--in", dest="src", required=True, help="已有计划 .md")
    r.add_argument("--today", required=True, help="今天 YYYY-MM-DD")
    r.add_argument("--done", default="", help="已完成日期，逗号分隔")
    r.add_argument("--out", dest="out", required=True, help="输出 .md 路径")
    r.add_argument("--available-days", dest="available_days", default="weekdays+weekend")

    args = ap.parse_args()
    if args.cmd == "reschedule":
        return cmd_reschedule(args)
    # 默认 build
    if not getattr(args, "spec", None):
        ap.error("请指定子命令 build 或 reschedule")
    cmd_build(args)


if __name__ == "__main__":
    raise SystemExit(main() or 0)
