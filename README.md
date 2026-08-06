# slice — 切片计划 Skill

把一个「大目标 / 课程提纲 / 长期任务」自动切成「每天可执行」的计划，并支持每日打卡、落后自动重排、导出日历。

适用场景：
- **目标型**：给我一个大目标 → 拆成每日计划；你可输入每天投入时长，也可不输入、让 skill 按截止日反推节奏。
- **课程型**：给我课程提纲 + 预计完成时间 → 拆成每天看多少内容 + 间隔复习（+1 / +3 / +7 天）。
- **通用长期任务型**：不限学习，任何长期任务都能切，重点是「可计划、不拖延」。

## 特性
- 统一目标卡片：描述 / 类型 / 截止日 / 每日时长(可选) / 可用日 / 优先级
- 双向排程：有截止日→反推每日负荷；无时长无截止日→默认节奏（不追问）
- 工作分解：里程碑 → 25–50 分钟原子任务
- 间隔复习：新内容后 +1 / +3 / +7 天自动排复习
- 缓冲与拖延防御：缓冲日 + 最小可执行单元 + 落后自动重排
- 每日打卡自动化：到点提醒、回报完成度、自动重排
- 导出（规划后**用户自选格式**）：Markdown / `.ics` 日历 / HTML 网页（带勾选框、可打印）/ 纯清单

## 安装
把本仓库的 `SKILL.md`、`references/`、`scripts/` 放到 WorkBuddy 的 skills 目录之一：

**用户级（所有项目可用）：**
```
复制到  ~/.workbuddy/skills/slice/
```

**项目级（仅当前仓库）：**
```
复制到  <你的项目>/.workbuddy/skills/slice/
```

即可在对话中说「帮我把 X 切成每天计划」「把这门课排进日程（X 月 X 日前学完）」触发，或 `/slice` 手动调用。

## 用法示例
- 目标型：`/slice 三个月学会 Python 做数据分析`（不填每日时长 → 按 3 个月窗口反推）
- 课程型：`/slice-course 提纲... 截止 2026-11-01`
- 自然语言：「帮我把写书的计划切成每天该做什么」

## 导出（规划后由用户选择格式）

规划完成后，skill 会主动询问你要哪种导出格式，**默认推荐 Markdown**，不会一股脑只吐 `.ics`：

| 格式 | 命令 / 产物 | 适合谁 | 怎么打开 |
|------|------------|--------|----------|
| **① Markdown（默认）** | 计划本身就是 `.md` 文件 | 所有人；最通用 | 记事本 / VS Code / 任意文本编辑器 |
| **② HTML 网页** | `export_html.py` → `xxx.html` | 想双击即看、带勾选框、可打印 | **浏览器直接双击打开**，无需装任何软件 |
| **③ .ics 日历** | `export_ics.py` → `xxx.ics` | 要导入手机/桌面日历、每天弹提醒 | 日历 App（苹果日历 / Google 日历 / Outlook）导入 |
| **④ 纯清单** | 计划文件里的勾选表 | 想手抄 / 贴到别处 | 同 Markdown |

脚本调用（参数与上面的 JSON 事件文件一致，仅依赖 Python 标准库）：
```
# HTML 网页（带勾选框，浏览器打开）
python scripts/export_html.py --in plans/xxx-events.json --out xxx.html --name "我的计划"

# .ics 日历（导入手机日历）
python scripts/export_ics.py --in plans/xxx-events.json --out xxx.ics
```

> 推荐给电脑端用户的路径：选 **Markdown 或 HTML** 即可，无需折腾日历 App。

## 文件结构
```
slice/
├── SKILL.md              # skill 工作流与触发规则（AI 读取后照做）
├── references/
│   ├── plan-template.md  # 计划文件标准格式
│   └── examples.md       # 三类场景完整示例
└── scripts/
    ├── export_ics.py     # 计划 → .ics 日历导出
    └── export_html.py    # 计划 → HTML 网页（带勾选框、可打印）
```

> 说明：当前排程逻辑由 `SKILL.md` 中的工作流说明驱动（AI 现推）。如需确定性、可复现的排程引擎，可后续把排程算法提取为 `scripts/` 下的正式脚本。

## 在 Claude Code / Codex 中使用

本仓库同时附带**可移植版本**，逻辑与 WorkBuddy 版完全一致（共用同一套工作流与脚本），但不依赖 WorkBuddy 专有功能：

- **Claude Code**：`portable/claude-code/` 是原生 skill 目录（已改写 frontmatter、去除 WorkBuddy 专属表述）。把它整体复制到 `~/.claude/skills/slice/`（全局）或 `<项目>/.claude/skills/slice/`（项目级），重启 Claude Code 即可用「帮我把 X 切成每天计划」触发。每日打卡可用 `/cron` 定时或手动触发。
- **Codex**：`portable/codex-slice.md` 是一段常驻指令。把它**追加**到 `~/.codex/AGENTS.md` 或项目根 `AGENTS.md`，Codex 会读取 `portable/claude-code/SKILL.md` 执行。Codex 无定时能力，打卡需手动每天触发。

> 移植版不依赖 WorkBuddy 的自动化 API 与 `.workbuddy` 记忆，改为 `/cron` 或手动打卡；脚本零依赖，任何装有 Python 的环境都能跑。

## License
MIT — 见 [LICENSE](LICENSE)。
