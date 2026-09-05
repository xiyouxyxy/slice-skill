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
    "archetype": "coding",               # 可选；应试 exam / 编程 coding / 技能 skill /
                                          # 知识 knowledge / 项目 project / 习惯 habit
                                          # 不给则按 type 与关键词推断，拿不准建议显式给
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

# ---------------------------------------------------------------------------
# 目标原型（archetype）：决定话术与验收手段
#
# 不同原型的验收逻辑本质不同，不能用一套话术通吃：
#   应试型 —— 验收是分数；**真题是消耗品**，复习要"复盘错题 + 换新题"，重做原题无效
#   编程型 —— 验收是"能跑通的代码"
#   技能型 —— 验收是"作品对比"，核心在手感（讲得清 ≠ 手会）
#   知识型 —— 验收是"讲给别人听"
#   项目型 —— 验收是"里程碑交付物"
#   习惯型 —— 验收是"当日动作 + streak"
# ---------------------------------------------------------------------------

_ARCHETYPE_DEFAULT = {
    "label": "通用",
    "review_sub": "能不看资料说出 {name} 的核心点",
    "review_accept": "重做关键验收项（{items}）",
    "review_std": "达到首次同等标准",
    "global_accept": "重做此前任意 2 个验收项",
    "buffer_accept": "任选之前的 1 个子目标重新过一遍 / 重做 1 个验收项",
    "buffer_recite": "任意 1 个旧难点，用自己的话讲清",
}

ARCHETYPE_PROFILE = {
    "exam": {
        "label": "应试型",
        "review_sub": "能说出本阶段错题的共同失分原因",
        "review_accept": "复盘本阶段错题（{items}）并补 1 套同等难度新题",
        "review_std": "正确率不低于首次 / 达到目标分数段",
        "global_accept": "复盘错题本 + 补 1 套跨阶段新题",
        # 轮做制：间隔拉长（>=30 天，答案印象已模糊）后二刷真题，检验真实内化
        "revisit_accept": "二刷此前做过的整套真题（间隔已久，检验真实内化而非记答案）",
        "revisit_std": "对比首刷，标出仍然做错的题并复盘失分原因",
        "buffer_accept": "整理错题本 / 补 1 组薄弱项专项练习",
        "buffer_recite": "讲清 1 道曾经的错题当时为什么错",
    },
    "coding": {
        "label": "编程 / 技术型",
        "review_sub": "能不看资料写出 {name} 的核心代码结构",
        "review_accept": "重跑关键代码（{items}）",
        "review_std": "能跑通",
        "global_accept": "重跑此前任意 2 段关键代码",
        "buffer_accept": "任选之前的 1 个子目标重新过一遍 / 重跑 1 段代码",
        "buffer_recite": "任意 1 个旧难点，讲清原理",
    },
    "skill": {
        "label": "动手技能型",
        "review_sub": "能不看资料做出 {name} 的核心动作",
        "review_accept": "重做关键练习（{items}）",
        "review_std": "与上次作品对比有可见进步",
        "global_accept": "重做此前任意 2 个练习",
        "buffer_accept": "补完未完成的作品 / 重做 1 个练习",
        "buffer_recite": "讲清 1 个动作要领（为什么必须这样做）",
    },
    "knowledge": {
        "label": "知识 / 理论型",
        "review_sub": "能不看资料复述 {name} 的核心概念",
        "review_accept": "不查资料复述关键概念（{items}）",
        "review_std": "能用自己的话讲清",
        "global_accept": "不查资料复述此前任意 2 个核心概念",
        "buffer_accept": "任选之前的 1 个子目标重新过一遍 / 讲给他人听",
        "buffer_recite": "任意 1 个旧难点，用自己的话讲清",
    },
    "project": {
        "label": "项目型",
        "review_sub": "能说清 {name} 交付物的完成标准",
        "review_accept": "重做关键交付物（{items}）",
        "review_std": "达到首次同等完成度",
        "global_accept": "复此前任意 2 个交付物",
        "buffer_accept": "推进 1 项未完成的交付物 / 重做 1 个验收项",
        "buffer_recite": "任意 1 个旧难点，用自己的话讲清",
    },
    "habit": {
        "label": "习惯型",
        "review_sub": "能说清本阶段坚持得最好与最差的各 1 天",
        "review_accept": "完成当日动作（{items}）",
        "review_std": "完成即可，重点是不断链",
        "global_accept": "连续完成当日动作，保住 streak",
        "buffer_accept": "完成最低限度的当日动作（保住 streak）",
        "buffer_recite": "讲清 1 个最容易打断你的场景与应对方式",
    },
}

_TYPE_TO_ARCHETYPE = {
    "应试": "exam", "考试": "exam", "备考": "exam",
    "编程": "coding", "技术": "coding",
    "技能": "skill", "手艺": "skill",
    "知识": "knowledge", "理论": "knowledge",
    "项目": "project",
    "习惯": "habit",
}

# 关键词兜底：仅在既没显式给 archetype、type 又无法映射时使用
_ARCHETYPE_KEYWORDS = [
    ("exam", ("雅思", "托福", "考研", "考证", "考试", "真题", "分数线", "及格", "gre", "证书", "上岸")),
    ("coding", ("python", "java", "javascript", "代码", "编程", "开发", "框架", "react", "前端", "后端", "算法", "github")),
    ("skill", ("画", "弹", "吉他", "钢琴", "做菜", "烹饪", "烘焙", "瑜伽", "游泳", "摄影", "手工", "书法", "舞蹈")),
]


def _infer_archetype(spec: dict) -> str:
    """推断目标原型；返回 "" 表示回落到通用模板。"""
    meta = spec.get("meta", {}) or {}
    a = str(meta.get("archetype") or "").strip().lower()
    if a in ARCHETYPE_PROFILE:
        return a
    t = str(meta.get("type") or "").strip()
    if t in _TYPE_TO_ARCHETYPE:
        return _TYPE_TO_ARCHETYPE[t]
    text = " ".join([
        str(meta.get("title") or ""),
        str(meta.get("complete_def") or ""),
        " ".join(str(m.get("name") or "") for m in spec.get("milestones", []) or []),
    ]).lower()
    for key, words in _ARCHETYPE_KEYWORDS:
        for w in words:
            if w.lower() in text:
                return key
    return ""


def _profile(archetype: str) -> dict:
    return ARCHETYPE_PROFILE.get(archetype, _ARCHETYPE_DEFAULT)


def _tpl(tpl: str, **kw) -> str:
    """安全地格式化话术模板；模板里没有对应占位符时原样返回。"""
    try:
        return tpl.format(**kw)
    except (KeyError, IndexError, ValueError):
        return tpl


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


def _to_hours(v):
    """把 1 / 1.0 / "1h" / "0.5h" 统一解析成 float 小时；无法解析或非正返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if float(v) > 0 else None
    s = str(v).strip().lower().rstrip("h").strip()
    try:
        h = float(s)
    except (TypeError, ValueError):
        return None
    return h if h > 0 else None


def _over_budget_items(sched: list, daily_h):
    """返回时长超过每日预算的 (item, hours) 列表，按超出幅度降序。

    步骤 3/5 承诺"每日时长决定任务颗粒度上限"，这里把该约束落地：
    单任务时长超过预算即预警，提示拆分或提高投入。
    """
    if not daily_h or daily_h <= 0:
        return []
    over = []
    for it in sched:
        # 全真模考的时长 = 整场考试时长（如雅思笔试 2h45m），是固定开销而非学习投入，豁免
        if "全真模考" in str(it.get("title", "")):
            continue
        h = _to_hours(it.get("duration"))
        if h is not None and h > daily_h + 1e-9:
            over.append((it, h))
    return sorted(over, key=lambda x: -x[1])


# ---------------------------------------------------------------------------
# 1. 把 spec 展开成有序的"日程项"列表（含自动生成的复习/缓冲）
# ---------------------------------------------------------------------------
def build_items(spec: dict, archetype: str = "") -> list:
    """返回有序 item 列表：每个 item 是带渲染所需字段的 dict。"""
    milestones = spec.get("milestones", [])
    items = []
    new_since_buffer = 0
    global_review_idx = 0

    for mi, m in enumerate(milestones):
        mname = m.get("name", f"M{mi + 1}")
        tasks = m.get("tasks", [])
        # 只有大里程碑（>6 任务）才允许在内部插缓冲，其余一律等到里程碑边界
        large = len(tasks) > 6
        for ti, t in enumerate(tasks):
            kind = t.get("kind", "新内容") or "新内容"
            items.append({
                "kind": kind,
                "title": f"{mname} · {t.get('title', f'任务{ti + 1}')}",
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
            is_last = (ti == len(tasks) - 1)
            # 里程碑内部插缓冲：仅限大里程碑；技能型一律不在内部插
            # （一幅画的"铺色 → 等干 → 刻画"不能被缓冲日拆到隔天）
            if new_since_buffer >= 5 and not is_last and large and archetype != "skill":
                items.append(_buffer_item(archetype))
                new_since_buffer = 0

        # 里程碑边界：统一在此结算，避免打断里程碑内部的连续任务
        if new_since_buffer >= 5:
            items.append(_buffer_item(archetype))
            new_since_buffer = 0

        # 里程碑末 +1 复习（覆盖本里程碑）
        items.append(_milestone_review(mname, mi, tasks, archetype))

        # 每 2 个里程碑插一次全局间隔复习（+3 / +7 / …）
        if (mi + 1) % 2 == 0 and global_review_idx < len(_GLOBAL_REVIEW_INTERVALS):
            span = _GLOBAL_REVIEW_INTERVALS[global_review_idx]
            global_review_idx += 1
            items.append(_global_review(mi, span, milestones, archetype))

    return items


def _buffer_item(archetype: str = "") -> dict:
    prof = _profile(archetype)
    return {
        "kind": "缓冲",
        "title": "缓冲日",
        "duration": None,
        "sub": ["不强求，做完三件套之一即可"],
        "accept": [prof["buffer_accept"]],
        "recite": [prof["buffer_recite"]],
        "milestone": "",
        "milestone_idx": -1,
    }


def _milestone_review(mname: str, mi: int, tasks: list, archetype: str = "") -> dict:
    # 从本里程碑任务里挑验收项，按原型套用对应话术（无需 LLM 额外输入）
    prof = _profile(archetype)
    task_titles = [t.get("title", f"任务{i + 1}") for i, t in enumerate(tasks)]
    accepts = []
    for t in tasks:
        for a in t.get("accept", [])[:2]:
            accepts.append(a)
    accepts = accepts[:3]
    recite_src = []
    for t in tasks:
        recite_src += t.get("recite", [])[:1]
    recite = recite_src[:2] if recite_src else [f"口述『{mname} 中最易混的 1 个点』"]

    items_txt = " / ".join(accepts) if accepts else "本里程碑重点项"
    accept_txt = _tpl(prof["review_accept"], items=items_txt, name=mname)
    if prof["review_std"]:
        accept_txt = f"{accept_txt}，{prof['review_std']}"
    return {
        "kind": "复习",
        "title": f"复习 {mname} 全部（+1 间隔复习）",
        "duration": 0.5,
        "sub": [_tpl(prof["review_sub"], name=mname)],
        "accept": [accept_txt],
        "recite": recite,
        "milestone": mname,
        "milestone_idx": mi,
        # 动态指回本里程碑覆盖的原始任务（而非写死）
        "review_src": task_titles,
    }


def _global_review(upto_idx: int, span: int, milestones: list, archetype: str = "") -> dict:
    prof = _profile(archetype)
    covered = [m.get("name", f"M{i + 1}") for i, m in enumerate(milestones[:upto_idx + 1])]
    # 轮做制（应试型）：间隔 >= 30 天的复习改为"二刷真题"——答案印象已模糊，
    # 重做才有诊断价值；短间隔仍用"复盘错题 + 换新题"（刚做过就重做是背答案）
    revisit = prof.get("revisit_accept")
    is_revisit = bool(revisit and span >= _REVISIT_MIN_SPAN)
    if is_revisit:
        accept_txt = revisit
        std = prof.get("revisit_std") or prof["review_std"]
        title = f"全局复习（+{span} 间隔，二刷真题，覆盖 {' / '.join(covered)}）"
        duration = 2.0  # 二刷是重做整套真题，需要完整时段，而非 0.5h 快过
    else:
        accept_txt = prof["global_accept"]
        std = prof["review_std"]
        title = f"全局复习（+{span} 间隔，覆盖 {' / '.join(covered)}）"
        duration = 0.5
    if std:
        accept_txt = f"{accept_txt}，{std}"
    return {
        "kind": "复习",
        "title": title,
        "duration": duration,
        "sub": [f"能串联 {(' / '.join(covered))} 的主线"],
        "accept": [accept_txt],
        "recite": [f"口述『{covered[-1]} 与 {covered[0]} 的关系』"],
        "milestone": "",
        "milestone_idx": -1,
        # 动态指回覆盖到的里程碑（而非写死）
        "review_src": covered,
    }


# ---------------------------------------------------------------------------
# 2. 排程：把有序 item 分配到可用日（Step 5）—— 双向适配
# ---------------------------------------------------------------------------
# 任务量少于可用日超过该比例时，视为"时间太多"，自动铺满到截止日
_SPREAD_THRESHOLD = 1.3

# 间隔达到该天数（约 4 周）后，应试型复习从"复盘+新题"切换为"二刷真题"
# （答案印象已模糊，重做才有诊断价值；刚做完就重做是背答案）
_REVISIT_MIN_SPAN = 30


def schedule(items: list, start: date, available_days: str, target_date=None,
             spec: dict = None, archetype: str = ""):
    """返回 (sched, overload, fill_log)。

    - 默认：1 个 item / 可用日（符合默认节奏"每天 1 原子任务"）。
    - 时间不够（可用日 < 任务数）：在可用日里尽量均摊，单日可合并多项并标记 overload。
    - 时间太多（可用日 > 任务数 × 阈值 且给了 spec）：自动补充轮次铺满到截止日，
      并把补了什么记入 fill_log（写进 .md 说明块 + 命令行打印）。
    """
    sched = []
    fill_log = []
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
            return sched, overload, fill_log

        # 时间太多：任务量撑不满截止日前的可用日 → 自动补轮次铺满
        if avail_count > len(items) * _SPREAD_THRESHOLD and spec:
            items, fill_log = _spread_items(items, spec, archetype,
                                            avail_count - len(items), tgt)

    # 铺满模式（有截止日且补过轮次）：模考锁定到考前日期，其余任务均匀分布到截止日
    if fill_log and target_date:
        tgt = datetime.strptime(target_date, "%Y-%m-%d").date()
        day_list = []
        cur = _next_available(start, available_days)
        while cur <= tgt:
            if _is_available(cur, available_days):
                day_list.append(cur)
            cur += timedelta(days=1)

        fixed_items = [it for it in items if it.get("_fixed_date")]
        free_items = [it for it in items if not it.get("_fixed_date")]

        used_days = set()
        for it in fixed_items:
            want = datetime.strptime(it["_fixed_date"], "%Y-%m-%d").date()
            pos = next((x for x in day_list if x >= want and x not in used_days), None)
            if pos is None:
                pos = next((x for x in reversed(day_list) if x not in used_days), None)
            if pos is not None:
                e = dict(it, date=pos)
                e.pop("_fixed_date", None)
                sched.append(e)
                used_days.add(pos)

        remaining = [x for x in day_list if x not in used_days]
        n = len(free_items)
        if n:
            if len(remaining) >= n:
                # 均匀分布：任务铺满整个周期，空隙自然成为消化间隔
                for k, it in enumerate(free_items):
                    p = min(int(k * len(remaining) / n), len(remaining) - 1)
                    sched.append(dict(it, date=remaining[p]))
            else:
                for k, it in enumerate(free_items):
                    sched.append(dict(it, date=remaining[min(k, len(remaining) - 1)]))
        sched.sort(key=lambda e: e["date"])
        return sched, overload, fill_log

    # 常规：1 item / 可用日
    for it in items:
        sched.append(dict(it, date=d))
        d = _advance(d, available_days)
    return sched, overload, fill_log


def _spread_items(items: list, spec: dict, archetype: str, need: int, target: date):
    """时间太多时，用额外轮次把计划铺满到截止日。返回 (新 items, fill_log)。

    补充优先级：
      1. 应试型：考前 30 / 14 / 7 天各插 1 次全真模考（带固定日期，不参与顺序排）；
      2. 追加更长间隔的复习轮次（+14 ~ +120），覆盖全部里程碑；
      3. 少量综合演练 / 专项补弱轮次；
      4. 仍有剩余 → 交给"均匀分布"消化（空隙即消化间隔）。
    """
    log = []
    out = list(items)
    milestones = spec.get("milestones", []) or []
    if not milestones:
        return items, log

    added_exams = added_reviews = added_drills = added_revisits = 0

    # 1) 应试型：模考节点（固定在考前日期）
    if archetype == "exam":
        for offset in (30, 14, 7):
            if need <= 0:
                break
            it = _mock_exam_item(offset)
            it["_fixed_date"] = (target - timedelta(days=offset)).isoformat()
            out.append(it)
            added_exams += 1
            need -= 1

    # 2) 追加间隔复习轮次
    for span in (14, 21, 30, 45, 60, 90, 120):
        if need <= 0:
            break
        out.append(_global_review(len(milestones) - 1, span, milestones, archetype))
        if archetype == "exam" and span >= _REVISIT_MIN_SPAN:
            added_revisits += 1
        added_reviews += 1
        need -= 1

    # 3) 少量综合演练（上限 8，其余交给均匀分布消化）
    idx = 1
    while need > 0 and idx <= 8:
        out.append(_drill_item(idx, archetype))
        added_drills += 1
        need -= 1
        idx += 1

    if added_exams:
        log.append(f"插入 {added_exams} 次全真模考（考前 30 / 14 / 7 天，固定日期）")
    if added_reviews:
        line = f"追加 {added_reviews} 个间隔复习轮次（+14 ~ +120 天，覆盖全部里程碑）"
        if added_revisits:
            line += f"，其中 {added_revisits} 个间隔 ≥ {_REVISIT_MIN_SPAN} 天的是二刷真题轮次"
        log.append(line)
    if added_drills:
        log.append(f"追加 {added_drills} 轮综合演练 / 专项补弱")
    if need > 0:
        log.append(f"其余 {need} 个空档日作为消化间隔（任务均匀分布到截止日）")

    return out, log


def _mock_exam_item(offset: int) -> dict:
    return {
        "kind": "复习",
        "title": f"全真模考（考前 {offset} 天）",
        "duration": 3.0,
        "sub": ["按正式考试的时长与流程完整走一遍，中途不查任何资料"],
        "accept": ["整套计时完成，记录总分与各单项分，并与上次模考对比"],
        "recite": ["口述『本次模考暴露的 3 个最大失分点与下一步对策』"],
        "milestone": "",
        "milestone_idx": -1,
        "review_src": [],
    }


def _drill_item(round_idx: int, archetype: str = "") -> dict:
    prof = _profile(archetype)
    return {
        "kind": "复习",
        "title": f"综合演练 / 专项补弱（第 {round_idx} 轮）",
        "duration": 1.0,
        "sub": ["挑目前最弱的 1 项集中练（先自评再动手）"],
        "accept": [prof["buffer_accept"]],
        "recite": [prof["buffer_recite"]],
        "milestone": "",
        "milestone_idx": -1,
        "review_src": [],
    }


def _advance(d: date, available_days: str) -> date:
    nxt = d + timedelta(days=1)
    return _next_available(nxt, available_days)


# ---------------------------------------------------------------------------
# 3. 渲染 .md（严格对齐 references/plan-template.md）
# ---------------------------------------------------------------------------
def render_md(spec: dict, sched: list, overload: bool, archetype: str = "", fill_log=None) -> str:
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
    if archetype:
        L.append(f"- 目标原型：{_profile(archetype)['label']}（{archetype}）")
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

    if fill_log:
        L.append(f"> **已自动铺满到截止日**：原始任务量少于可用日，引擎自动补充了 {len(fill_log)} 项——")
        for line in fill_log:
            L.append(f"> - {line}")
        L.append("")

    over_budget = _over_budget_items(sched, _to_hours(daily))
    if over_budget:
        names = "、".join(f"{it['title']}（{_fmt_duration(h)}）" for it, h in over_budget[:3])
        tail = f" 等共 {len(over_budget)} 个" if len(over_budget) > 3 else ""
        L.append(
            f"> ⚠️ **单任务超出每日预算**（{_fmt_duration(daily)}/天）：{names}{tail}。"
            f"建议拆成连续几天的切片，或提高每日投入。"
        )
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
    src = it.get("review_src")
    if src:
        # 用全角竖线分隔：任务标题本身可能含 "/"（如"平涂/干笔/点彩"），用 "/" 会被误切
        lines.append("- **复习指向**（回到这些原始任务）：" + " ｜ ".join(str(x) for x in src))
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
    archetype = _infer_archetype(spec)

    items = build_items(spec, archetype)
    sched, overload, fill_log = schedule(items, start, avail,
                                         meta.get("target_date"), spec, archetype)
    md = render_md(spec, sched, overload, archetype, fill_log)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)

    finish = sched[-1]["date"].isoformat() if sched else start_str
    note = " ⚠️时间紧(已合并日期)" if overload else ""
    print(f"生成计划：{args.out}")
    print(f"  任务项 {len(sched)} 个，预计完成日 {finish}{note}")
    if archetype:
        print(f"  目标原型：{_profile(archetype)['label']}（{archetype}）")
    if fill_log:
        print(f"  已自动铺满到截止日，补充 {len(fill_log)} 项：")
        for line in fill_log:
            print(f"     + {line}")
    over = _over_budget_items(sched, _to_hours(meta.get("daily_duration", 1.0)))
    if over:
        print(f"  ⚠️ {len(over)} 个任务超出每日预算 {_fmt_duration(meta.get('daily_duration', 1.0))}：")
        for it, h in over:
            print(f"     - {it['title']}（{_fmt_duration(h)}）")


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
