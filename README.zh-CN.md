# ccusage-viz

[English](README.md)

`ccusage-viz` 将 [`ccusage`](https://github.com/ryoppippi/ccusage) 的 Token 数据转换为终端原生图表，每次调用只绘制一张图。它面向使用 Claude Code、Codex 或自定义模型、希望按需查看用量或常驻轻量 Live Dashboard，但不想再引入一个用量数据库的用户。

> **状态：** `0.1.0` 是仍在本地开发的 Alpha 版本。代码已针对 `ccusage 20.0.20` 测试；项目不内置 `ccusage`。

## 为什么使用 ccusage-viz？

- **五种专注的视图** — 每日折线图、日历热力图、Token 构成堆叠图、累计排名和观测 TPM 监控。
- **只关注 Token** — 不监控费用、额度、QPM 或 API 速率限制。
- **无状态** — 读取 `ccusage` 命令输出，不扫描 Agent 原始日志，不创建用量数据库或持久缓存。
- **按需 Live** — Watch 默认每五秒刷新；Monitor 默认每 15 秒采样，并支持暂停和手动刷新。
- **保留项目来源** — 即使 Claude 与 Codex 的项目显示名相同，也仍是两个独立项目。
- **双语界面** — 内置英文与简体中文，并支持严格校验的局部文案覆盖。

所有图表命令都要求交互式终端；帮助与版本输出不要求 TTY。

## 快速开始

先用确定性的合成数据安全体验渲染效果。Demo 模式不会调用 `ccusage`，也不会写入用量数据：

```bash
uv run ccusage-viz timeline --demo
uv run ccusage-viz calendar --demo small
uv run ccusage-viz stack --demo large --split-cache
uv run ccusage-viz ranking --demo --by project
```

使用真实数据前，请先安装并配置 `ccusage`：

```bash
uv run ccusage-viz timeline
uv run ccusage-viz ranking --by model --days 30
```

## 安装

项目发布到 PyPI 后，推荐使用 pipx 安装：

```bash
pipx install ccusage-viz
ccusage-viz --version
ccuv --version
```

`ccuv` 是随包安装的 `ccusage-viz` 命令别名，两者行为完全相同。


### 从源码安装

此流程要求 Python 3.11–3.13 和 [`uv`](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/Cookie-HOO/ccusage-viz.git
cd ccusage-viz
uv sync --all-groups
uv run ccusage-viz --help
```

将源码目录安装为可编辑的命令行工具：

```bash
uv tool install -e .
ccusage-viz --version
```

`ccusage` 必须位于 `PATH` 中，也可以通过 `--ccusage-bin` 指定。应用的 Python 运行时依赖只有 `plotext`。

## 子命令

每次调用只绘制一张图。

| 子命令 | 默认范围 | 默认分组 | 默认 Top N | 输出 |
| --- | ---: | --- | ---: | --- |
| `timeline` | 14 天 | `total` | 分组视图为 3 | 一张每日折线图；分组时在同一张图中绘制多条线 |
| `calendar` | 365 天 | — | — | 周一开始、类似 GitHub、按正值四分位分为四档的每日热力图 |
| `stack` | 14 天 | Token 构成 | — | 输入、输出和合并缓存的每日堆叠柱状图 |
| `ranking` | 14 天 | `project` | 10 | 按总 Token 绘制横向条形排名，并在标题中显示实际生效的包含首尾日期范围 |
| `monitor` | 进程内 1 小时 | 权威总 TPM | — | 通过重复快照展示持续运行的观测 Token 吞吐率 |

所有日期范围都表示**包含首尾的自然日**。`--days 14` 表示今天和此前 13 天。`--until` 默认为今天；可用 IANA 时区名通过 `--timezone` 定义自然日边界。`--days` 不能与 `--since` 同时使用。

```bash
# 最近 14 天的一条总量折线
ccusage-viz timeline

# 同一张图中的 Top 3 模型（随包安装的别名行为相同）
ccuv timeline --by model

# Top 5 Agent，其他正数分组汇总后放在最后
ccusage-viz timeline --by agent --top 5 --show-other

# 使用指定自然日时区的有界范围
ccusage-viz calendar --since 2026-01-01 --until 2026-03-31 \
  --timezone America/Los_Angeles

# 不再合并缓存读取与缓存创建
ccusage-viz stack --days 30 --split-cache

# Agent 作用域下的项目排名
ccusage-viz ranking --by project --top 20
```

`--top` 必须为正数；对 Monitor，`--top` 只能与 `--by model` 一起使用。程序先筛选，再分组并计算 Top N。Top N 外的筛选后分组默认隐藏；设置 `--show-other` 后，只把这些被 Top N 排除的分组合并为 `Other`。`Other` 不占 Top 名额且始终放在最后。如果筛选后没有分组落在 Top N 之外，程序不会绘制空的 `Other`，而会显示原因提示。如需近似无限制，可以使用 `--top 999` 之类的大值。

### 筛选与分组

可以把一次刷新中的输入理解为一张只存在于内存中的虚拟表：

```text
date | agent | model | project | input | output | cache_read | cache_creation | total
```

普通指标是 `SUM(totalTokens)`。`--by` 类似 `GROUP BY`；`--agent`、`--model`、`--project` 类似 `WHERE`；`--top N` 类似 `ORDER BY SUM(totalTokens) DESC LIMIT N`。`stack` 是例外：它分别聚合各 Token 构成。

筛选器可以重复：

```bash
ccusage-viz timeline --by model --agent claude --model sonnet --model opus
ccusage-viz ranking --by project --project project-a --project project-b
```

同一维度内的多个筛选器按 OR 组合，不同维度按 AND 组合。匹配忽略大小写，并先尝试精确匹配；唯一的包含匹配会被接受，多个不同的包含候选会提示歧义并要求输入更多文本。

模型筛选和分组使用上游真实 `modelBreakdowns`，不会按比例分摊 Token。有效结果中缺失的日期或构成补零。如果所选 Agent、模型或项目在范围内没有数据，程序会继续绘制可用图表，并通过提示指出无数据的选项。`totalTokens` 与已知构成之间的正残差显示为 `Other`；如果构成合计超过上游总量，则视为不兼容的 Schema 数据。

### 项目标识与能力限制

项目标识为 `(agent, 上游不透明项目 ID)`。不同 Agent 下的项目不会自动合并。即使两个 Agent 给出了相同显示名，按项目分组时也仍分别绘制。因此，`--project project-a` 这样的精确筛选可能同时选中不同 Agent 下的同名项目；可再加 `--agent claude` 或 `--agent codex` 缩小候选范围。

程序不会把 Claude 的不透明实例 ID 解码成猜测路径。若 ccusage 提供的是路径编码的不透明标识，会显示其中最终的项目片段；否则当前视图会分配中性的 `Project N` 别名。真实的路径形式 ID 可以使用 basename 作为显示名，但标识始终保留上游原始值。

当前 `ccusage 20.0.20` 在不同视图下的能力如下：

| 视图 | 每次刷新查询数 | 说明 |
| --- | ---: | --- |
| 普通非项目视图 | 1 | `ccusage daily --by-agent --json … --offline --no-cost` |
| 需要项目数据的 `timeline`、`calendar` 或 `stack` | 1 | 使用 Claude 有界每日实例数据；通过能力提示说明已省略 Codex |
| `ranking --by project` 或带项目筛选的 ranking | 并行 2 次 | 固定的 Claude 每日实例查询，以及固定的 Codex session 查询 |

Ranking 的双查询路径是固定的数据源计划，不会按日期、Agent、模型或项目循环调用。Claude session 总量不会用于有界统计，因为 `ccusage 20.0.20` 可能把命中 session 中范围外的用量也计入；Codex session 筛选是事件级有界筛选。

### 每日对比摘要

`calendar` 和 `timeline` 会在默认范围、`--days` 或只显式指定一个日期边界时显示一条本地化摘要。`--no-summary` 可隐藏 timeline、calendar 和 stack 的摘要。同时指定 `--since` 和 `--until` 的固定历史范围不显示摘要。Calendar 对比图中显示的每日汇总总量；Timeline 只汇总实际绘制的线，包括可见的“其他”线，同时排除被 Top N 隐藏的分组。

摘要值在适用处使用固定四位小数的紧凑 Token 格式。摘要将当前范围最后一天分别与前一天、七天前同一星期几对比，并在这些当前日期视图中沿用本地化的“今天”文案。短范围之外的对比日期与源数据缺失日期一样按零处理。基准值为正时使用保留一位小数的百分比变化；数值相等时显示“持平”且不附加百分比；零基准增长为正数时显示“从 0 增至当前值”；正基准降为零时显示下降 100%。当前值固定使用青色强调，上升使用绿色，下降使用在明暗终端背景上都更清晰的深琥珀色，不随图表配色变化；`mono` 仍保持灰阶。完整句子、各片段、标点和占位符都可以通过严格语言覆盖目录调整。


## Monitor

```bash
ccusage-viz monitor
ccusage-viz monitor --by model --top 2
ccusage-viz monitor --interval 20 --window 2h
ccusage-viz monitor --demo small
```

`monitor` 是常驻、进程内的观测视图。第一次成功的累计 `ccusage` 快照只建立基线；随后快照使用单调时钟的实际间隔进行差分。因此它在启动前没有任何读数，不能重建过去 24 小时图表。进程内原生历史以分钟汇总，最多保留 24 小时；显示窗口默认为 1 小时，可在 5 分钟到 24 小时之间调整。`--window` 只保留当前进程观测到的历史（5m–24h，默认 `1h`）；真实监控的 `--interval` 默认 15 秒。Demo Monitor 未显式指定 `--interval` 时以 1 秒的合成节奏推进；隐藏的 `--timeout` 限制单个 `ccusage` 子进程的最大时长。

省略 `--by` 时显示权威的**总 TPM**；`--by model` 与 `--by agent` 分别显示对应的 TPM 投影；`--by project` 显示每个项目从可见窗口左边界开始的累计 Token 增长。分组 Monitor 默认保留 Top 3，其余合并到 `Other`。`--agent`、`--model` 与 `--project` 都是仅启动时生效的数据源筛选。快捷键：`q` 退出、`r` 立即采样、Space 暂停/恢复、`m` 打开固定两行的运行时调整面板。面板可调整窗口、间隔、分组、Top、主题和样式，不会重新查询或丢失已保留历史；`y` 会复制候选命令。Monitor 横轴使用 `HH:MM` 标签。可用 `--theme` 和 `--style` 指定初始外观；Monitor 有意不支持启动时 `--pick`，因为真实观测历史尚不存在——要立即比较样式请使用 `monitor --demo`。Demo Monitor 数据是确定性的，启动即有波动的内存历史，绝不调用 `ccusage`。

观测 TPM 不等同于 QPM，也不等同于 API 速率限制 TPM；当前没有 QPM 指标。未来若加入外部 QPM，将统计逻辑请求，绝不会从 Token 或重试次数推断请求数。它不宣称提供历史逐分钟数据、任意日期范围的小时分布或启动前的滚动窗口。采样间隙、查询错误和计数器回退不会被伪装成零流量。

## Watch 模式

```bash
ccusage-viz timeline --watch       # 5 秒
ccusage-viz timeline --watch 10    # 10 秒
```

最小间隔为两秒。等待从上一次刷新完成后开始，因此不同刷新不会重叠。Watch 会在终端最后一行持续显示精简快捷键提醒；Demo 模式还会显示数据档位按键。快捷键：

- `q` — 退出，并取消此进程拥有的 `ccusage` 子进程。
- `r` — 立即刷新；如果正在刷新，最多再排队一次。
- `Space` — 暂停或恢复自动刷新；暂停时仍可手动刷新。
- `s`、`m`、`l` — Watch Demo 时切换合成数据量级。

Watch 运行时使用完整可用终端高度，刷新重绘不追加尾随换行，因此不会在每次刷新时向上滚屏。状态固定在第一行，快捷键提醒固定在最后一行，警告提示带有警告符号和固定语义前景色，显示在快捷键上方。刷新期间保留原有状态文字，只在末尾追加低强调的“刷新中”，并且只更新第一行；按下 Space 也会立即更新该行，包括查询仍在执行时。新结果到达后才重绘图表。退出时只写入一个最终换行，让 Shell Prompt 从新行开始。一次性渲染则会为后续 Shell Prompt 预留一行，并继续把提示放在图表上方。刷新期间或后续出错时保留上一张成功图表。无数据和终端过小状态仍会存活，等待后续刷新。`--days 14` 这样的相对时间窗口会在所选自然日时区跨过午夜时前移；显式指定边界的范围保持不变。`Ctrl-C` 等同于退出，会恢复终端输入模式且不打印 traceback。

可以独立运行多个 Watch 进程。程序没有全局锁、Daemon、PID 文件、共享缓存或跨进程状态；每个实例只管理自己的子进程。并发实例也会独立运行 `ccusage` 扫描，因此 CPU、磁盘和内存开销会叠加。

### 暂缓小时与滚动历史视图

当前 `ccusage 20.0.20` JSON 无法准确支持小时历史：每日数据只有日期，Session 只有聚合总量而非分时数据，Claude blocks 是五小时计费窗口，而且 Claude/Codex 没有统一的请求次数字段。上游小时功能 PR [#724](https://github.com/ccusage/ccusage/pull/724) 已关闭且未合并，原 `blocks --live` 监控也已在 [#782](https://github.com/ccusage/ccusage/pull/782) 中删除。因此，ccusage-viz 不会宣称提供准确的滚动 24 小时峰值、小时使用习惯或调用量，也不会通过读取 Agent 原始日志、采样写入历史文件、运行 Collector 或创建用量数据库来绕过限制。准确小时视图需等待上游提供受支持的小时 JSON 契约。

## Demo 模式

```bash
ccusage-viz timeline --demo         # medium
ccusage-viz timeline --demo small
ccusage-viz timeline --demo medium
ccusage-viz timeline --demo large
```

生成的记录是确定性的。三个档位只改变数值量级，不改变日期、形状或标识；数据涵盖零值日期、峰值、单位边界、跨 Agent 同名项目、Token 残差和 Top 溢出。Demo 模式从不调用 `ccusage`，也不写入用量记录。

### 外观选择器与图表样式

Theme 负责语义前景色，Style 负责图表形态。两者都只在当前进程中生效：

```bash
ccusage-viz timeline --pick
ccusage-viz calendar --pick --theme github
ccusage-viz stack --pick --split-cache
ccusage-viz timeline --pick --demo small
ccusage-viz timeline --pick --watch 5
```

没有 `--demo` 时，选择器会按当前日期范围和筛选条件执行一次普通 `ccusage` 快照查询。指定 `--demo [small|medium|large]` 时，选择阶段和后续运行始终使用该档确定性合成数据，且绝不调用 `ccusage`。导航只会重新渲染保留在内存中的快照，不会重新查询或生成数据。

选择器始终只在屏幕上保留一张图。按 `n` 切换下一个主题，按 `p` 切换上一个主题，按 `j` 切换下一个样式，按 `k` 切换上一个样式，按 `y` 复制规范化后的候选命令，按 Enter 确认，按 `q` 或 Ctrl-C 取消，首尾循环；`--theme` 和 `--style` 指定初始外观。Ranking 也支持选择器；配合 `--no-color` 时仍可选择 Style，但 Theme 在视觉上不生效。不使用 Watch 时，确认后保留当前图表并退出；使用 Watch 时，当前快照成为第一张 Watch 图表，首次自动刷新等待一个完整间隔。

样式按子命令定义：Timeline 支持 `linear`、`step`、`stem`、`area`；Calendar 支持 `relative`、`absolute`；Stack 支持 `stacked`、`stacked-pattern`、`grouped`、`grouped-thin`、`normalized`；Ranking 支持 `bar`、`dot`、`dots`。`--ascii` 只改变字符，`--no-color` 移除 ANSI 样式；二者都不是 Theme 或 Style。

## 语言与终端行为

使用 `--lang en` 或 `--lang zh`。未指定时，Python 系统 Locale 中的 `zh_CN`、`zh_SG` 或 `Hans` 选择简体中文；繁体中文 Locale 与其他语言回退为英文。

可用 JSON 文件覆盖部分文案：

```bash
ccusage-viz timeline --lang zh --lang-file examples/language-overrides.json
```

覆盖文件可以只提供任意一部分已知 Key；未提供的 Key 继承所选内置语言。所提供的部分采用原子校验：必须是有效 UTF-8 JSON、顶层为对象、无重复或未知 Key、值为非空字符串，而且占位符名称、转换和格式必须完全一致；命名占位符可以调整顺序。Watch 模式只加载一次文件。全部 Key 和占位符参见[语言覆盖](docs/language-overrides.zh-CN.md)。

所有子命令都支持 `--theme classic|vivid|contrast|dracula|catppuccin|solarized|gruvbox|nord|github|mono`，默认为 `classic`。Dracula、Catppuccin、Solarized、Gruvbox、Nord 与 GitHub 是对成熟主题家族的 ANSI-256 精选适配，并非编辑器主题的逐值复刻。GitHub 主题为 Calendar 提供类似贡献图的四档绿色，并为所有命令提供完整语义色。主题只设置前景色，覆盖 Timeline 序列与“其他”、Calendar 强度、Stack 构成、Ranking 标记和诊断高亮。程序不推断终端品牌或明暗背景，因此继续继承终端背景。Timeline 会联合分配分类颜色并配合不同标记；Stack 使用冷暖混合分类色和不同构成字符，因此不会只依赖颜色区分。Calendar 使用有序的四档配色，而字符密度（`░▒▓█`，设置 `--ascii` 时为 `.oO#`）始终是从低到高的权威强度编码。

使用 `--no-color`（或 `NO_COLOR`）禁用全部样式，此时所选配色在视觉上不再生效；`--ascii` 只改变图形字符，不改变摘要文案。`TERM=dumb` 也会选择保守的终端行为。最小终端尺寸为：

| 子命令 | 最小尺寸 |
| --- | --- |
| `timeline` | 60×18 |
| `calendar` | 72×14 |
| `stack` | 60×18 |
| `ranking` | 60×12 |

## 推荐 Alias

```bash
alias cct='ccusage-viz timeline --watch'
alias ccm='ccusage-viz timeline --by model --days 30'
alias ccs='ccusage-viz stack --days 30 --split-cache'
alias ccp='ccusage-viz ranking --by project --days 30'
```

## 无状态与隐私边界

正常运行时，`ccusage-viz` 只消费 `ccusage` 命令输出。它**不会**：

- 直接读取 Claude Code、Codex 或其他 Agent 的原始日志；
- 创建用量数据库、索引、持久缓存或应用配置；
- 启动 Daemon 或创建 PID 文件；
- 计算费用、额度或速率限制；
- 提供 JSON、CSV、TSV 或表格输出；
- 持久化 Demo 或真实用量记录。

上游 Agent、模型和项目值可能出现在图表标签或诊断信息中。原始 `ccusage` stderr 不会被翻译。

## 开发

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check src/
uv run pytest
uv build
```

目标 Python 版本为 3.11、3.12 和 3.13。项目采用 `src/` 布局和 `uv_build` 后端。

## 发布元数据

此源码目录不表示已创建 GitHub Release 或已发布到 PyPI。计划中的 PyPI Trusted Publisher 配置为：

- 仓库：`Cookie-HOO/ccusage-viz`
- Workflow：`pypi-publish.yml`
- Environment：`pypi`

## 路线图与反馈

公开路线图见 [ROADMAP.md](ROADMAP.md)。请使用标准的[Bug 报告](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)或[功能请求](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)表单反馈可复现问题与明确需求。

## License

MIT，参见 [LICENSE](LICENSE)。
