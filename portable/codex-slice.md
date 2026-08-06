# Slice 切片计划（Codex 常驻指令）

> 用法：把本文件内容**追加**到你的 `AGENTS.md`（用户级 `~/.codex/AGENTS.md` 或项目根 `AGENTS.md`）。
> Codex 没有 skill 系统，按 `AGENTS.md` 常驻指令工作。本片段刻意保持极简——完整逻辑与 Claude Code 版共用同一份文件，避免两边漂移。

## 触发

当用户想把"大东西"切成"每天做的小事"时（典型句式）：
- "帮我把学 Python 切成每天计划"
- "把这门课的提纲排进日程（X 月 X 日前学完）"
- "制定一个减肥 / 备考 / 写书的每日计划"
- "把 X 拆成每日任务 / 切片 / 每天安排一点"

**第一步**：先用 Read 打开**本仓库内**的文件获取完整 10 步工作流并严格照做：
```
portable/claude-code/SKILL.md
```
（clone 仓库后路径即 `<你的仓库>/portable/claude-code/SKILL.md`。Claude Code 用户把 `portable/claude-code/` 整体复制到 `~/.claude/skills/slice/` 即可原生加载。）

## 辅助脚本（零依赖，纯 Python 标准库，位于仓库内）

- **HTML 导出**（双击浏览器打开、带勾选框、可打印，推荐给打不开 .ics 的用户）：
  ```
  python portable/claude-code/scripts/export_html.py --in events.json --out plan.html --name "计划名"
  ```
- **ICS 日历导出**（导入手机/桌面日历）：
  ```
  python portable/claude-code/scripts/export_ics.py --in events.json --out plan.ics
  ```
- 输入 `events.json` 为事件数组，每行形如 `{"date":"YYYY-MM-DD","title":"...","desc":"..."}`。

## 与 Claude Code 版的差异（Codex 环境须知）

- **无定时打卡**：Codex 没有自动化/定时能力。每日打卡请用户**每天手动**让 Codex 读取计划文件并执行 `SKILL.md` 步骤 9（标记完成度 + 落后自动重排）。
- **计划落盘**：沿用 `SKILL.md` 里的 `.slice/plans/<goal-slug>.md`，或你喜欢的任意路径。
- 其余工作流（WBS、双向排程、间隔复习、缓冲、导出选格式）与 Claude Code 版完全一致。
