# ccusage-viz

[English](README.md) · [设计哲学](docs/design-philosophy.zh-CN.md)

`ccusage-viz` 将 [`ccusage`](https://github.com/ryoppippi/ccusage) 的 Token 数据转换为终端原生图表，每次调用只绘制一张图。它面向使用 Claude Code、Codex 或自定义模型、希望按需查看用量或常驻轻量 Live Dashboard，但不想再引入一个用量数据库的用户。

> **状态：** `0.1.0` 是仍在本地开发的 Alpha 版本。版本号采用 `主版本.次版本.修订号`；从 `1.x.x` 开始提供稳定兼容性。在 `0.x.x` 阶段，CLI、TUI、数据及其他公开接口均可能发生不兼容变更，欢迎通过 Issue 提出反馈。代码已针对 `ccusage 20.0.20` 测试；项目不内置 `ccusage`。

## 为什么使用 ccusage-viz？

- **五种专注的视图** — 每日折线图、日历热力图、Token 构成堆叠图、累计排名和观测 TPM 监控。
- **只关注 Token** — 不监控费用、额度、QPM 或 API 速率限制。
- **无状态** — 读取 `ccusage` 命令输出，不扫描 Agent 原始日志，不创建用量数据库或持久缓存。
- **按需 Live** — 历史图表默认每 10 秒刷新；Monitor 默认每 15 秒采样，并支持暂停和手动刷新。
- **保留项目来源** — 即使 Claude 与 Codex 的项目显示名相同，也仍是两个独立项目。
- **双语界面** — 内置英文与简体中文。

所有图表命令都要求交互式终端；帮助与版本输出不要求 TTY。

## 快速开始

先用确定性的合成数据安全体验渲染效果。Demo 模式不会调用 `ccusage`，也不会写入用量数据：

```bash
uv run ccuv timeline --demo
uv run ccuv calendar --demo small
uv run ccuv stack --demo large --cache split
uv run ccuv ranking --demo --by project
```

使用真实数据前，请先安装并配置 `ccusage`：

```bash
uv run ccuv timeline
uv run ccuv ranking --by model --period 30d
```

## 安装

项目发布到 PyPI 后，推荐使用 pipx 安装：

```bash
pipx install ccusage-viz
ccuv --version
ccuv --version
```

`ccuv` 是随包安装的 `ccusage-viz` 命令别名，两者行为完全相同。


### 从源码安装

此流程要求 Python 3.11–3.13 和 [`uv`](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/Cookie-HOO/ccusage-viz.git
cd ccusage-viz
uv sync --all-groups
uv run ccuv --help
```

将源码目录安装为可编辑的命令行工具：

```bash
uv tool install -e .
ccuv --version
```

`ccusage` 必须位于 `PATH` 中，也可以通过 `--ccusage-bin` 指定。如果交互式终端中缺少默认的 `ccusage` 命令，ccuv 会显示准确命令 `npm install -g ccusage`；只有直接按空 Enter 才会执行安装，成功后继续原命令。Ctrl-C、EOF 或输入任意文字都会取消。Demo、重定向/非交互执行以及自定义 `--ccusage-bin` 绝不会触发安装；npm 不可用时请手动安装，npm 成功但命令仍不可见时请重启终端或更新 `PATH`。应用的 Python 运行时依赖只有 `plotext`。

## 子命令

每个渲染子命令生成一张图；`dashboard` 在同一终端中组合多个独立刷新的图表。

| 子命令 | 默认范围 | 默认分组 | 默认 Top N | 输出 |
| --- | ---: | --- | ---: | --- |
| `timeline` | 14 天 | `total` | 分组视图为 3 | 一张每日折线图；分组时在同一张图中绘制多条线 |
| `calendar` | 365 天 | — | — | 周一开始、类似 GitHub、按正值四分位分为四档的每日热力图 |
| `stack` | 14 天 | Token 构成 | — | 输入、输出和合并缓存的每日堆叠柱状图 |
| `ranking` | 14 天 | `project` | 10 | 按总 Token 绘制横向条形排名，并在标题中显示实际生效的包含首尾日期范围 |
| `monitor` | 进程内 1 小时 | 权威总 TPM | — | 通过重复快照展示持续运行的观测 Token 吞吐率 |
| `dashboard` | 各子图独立 | 时间趋势、Token 构成、排名、监测 | 各子图独立 | 仅调整时选择目标、各子图独立刷新的仪表盘 |

所有日期范围都表示**包含首尾的自然日**。`--period 14d` 表示今天和此前 13 天。滚动范围标题显示规范化周期（例如 `时间趋势 · 14d`）；同时显式给出 `--since` 和 `--until` 的固定范围则显示实际生效日期。`--until` 默认为今天；可用 IANA 时区名通过 `--timezone` 定义自然日边界。`--period` 不能与 `--since` 同时使用。

```bash
# 最近 14 天的一条总量折线
ccuv timeline

# 同一张图中的 Top 3 模型（随包安装的别名行为相同）
ccuv timeline --by model

# Top 5 Agent，其他正数分组汇总后放在最后
ccuv timeline --by agent --top 5 --other show

# 使用指定自然日时区的有界范围
ccuv calendar --since 2026-01-01 --until 2026-03-31 \
  --timezone America/Los_Angeles

# 不再合并缓存读取与缓存创建
ccuv stack --period 30d --cache split

# Agent 作用域下的项目排名
ccuv ranking --by project --top 20
```

`--top` 必须为正数；对 Monitor，`--top` 需要与 `--by agent`、`--by model` 或 `--by project` 一起使用。程序先筛选，再分组并计算 Top N。Top N 外的筛选后分组默认隐藏；设置 `--other show` 后，只把这些被 Top N 排除的分组合并为 `Other`。`Other` 不占 Top 名额且始终放在最后。如果筛选后没有分组落在 Top N 之外，程序不会绘制空的 `Other`，而会显示原因提示。如需近似无限制，可以使用 `--top 999` 之类的大值。在 Watch 或 Dashboard 刷新中，Ranking 会分开表达三类变化：只有稳定条目名次上升或下降时，排名旁才显示箭头；项目名前的高亮 `●`（`--ascii` 下为 `*`）表示数值有活动变化；数值旁的 `↑`、`↓` 或 `—` 表示累计 Token 相对上一次成功接收的刷新增长、下降或持平（`--ascii` 下为 `^`、`v` 或 `=`）。初始基线不显示标记；基线后首次出现的条目显示活动和数值上升标记，但不会伪造排名箭头，`Other` 也不会显示排名变化。

### 筛选与分组

可以把一次刷新中的输入理解为一张只存在于内存中的虚拟表：

```text
date | agent | model | project | input | output | cache_read | cache_creation | total
```

普通指标是 `SUM(totalTokens)`。`--by` 类似 `GROUP BY`；`--agent`、`--model`、`--project` 类似 `WHERE`；`--top N` 类似 `ORDER BY SUM(totalTokens) DESC LIMIT N`。`stack` 是例外：它分别聚合各 Token 构成。

筛选器可以重复：

```bash
ccuv timeline --by model --agent claude --model sonnet --model opus
ccuv ranking --by project --project project-a --project project-b
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

### 周期对比摘要

`timeline` 和 `stack` 使用 `--granularity day|month|quarter|year`；运行时按 `g` 只切换粒度，不改变所选 Period 或日期范围。`calendar` 和 `ranking` 保持每日粒度。Period 可独立使用 `d`、`mo`、`q` 和 `y`，因此任意粒度下显式 `--period 12mo` 都有效。同时指定 `--since` 和 `--until` 会得到固定范围。摘要始终聚合当前完整筛选范围，不受 Top N 展示裁剪影响；当 Top N 隐藏尾部分组且未启用 `Other` 时，会标注为“当前筛选总量”并说明图表只显示 Top N。

日摘要对比今天、昨天以及七天前同一星期几。月和季度按截至当前的已过天数，分别与上一周期同期、去年同期对比；年摘要对比今年至今与去年同期。计算使用自然月、自然季度和自然年边界，而不是固定减去 30/90/365 天；较短周期会自动截断。独立命令和 Dashboard 子图只使用图表已经加载的记录，绝不会为了摘要单独查询。

覆盖范围来自成功请求的区间，即使响应为空也算覆盖；不会从返回记录的首尾日期推断。覆盖区间内缺失的行是真实零值，区间外则是未知。显示普通数值摘要前必须覆盖当前周期，而每个缺失覆盖的对比片段会独立隐藏。持平使用中性标记 `—`（`--ascii` 下为 `=`）；零基准增长显示“从 0”并使用上升标记；正基准降为零显示下降 100%。完整句子、各片段、标点和占位符均在内置英文与简体中文目录中本地化。

Calendar 的指标页脚固定为三条逻辑行：活跃天数/当前连续/最长连续；日均及可选峰值；热力图例。没有峰值时日均仍会保留，窄终端会逐行独立裁剪。


## Monitor

```bash
ccuv monitor
ccuv monitor --by model --top 2
ccuv monitor --interval 20 --window 2h
ccuv monitor --demo small
```

`monitor` 是常驻、进程内的观测视图。第一次成功的累计 `ccusage` 快照只建立基线；随后快照使用单调时钟的实际间隔进行差分。因此它在启动前没有任何读数，不能重建过去 24 小时图表。进程内原生历史以分钟汇总，最多保留 24 小时；显示窗口默认为 1 小时，可在 5 分钟到 24 小时之间调整。`--window` 只保留当前进程观测到的历史（5m–24h，默认 `1h`）；真实监控的 `--interval` 默认 15 秒。Demo Monitor 未显式指定 `--interval` 时以 1 秒的合成节奏推进；隐藏的 `--query-timeout` 限制单个 `ccusage` 子进程的最大时长。

省略 `--by` 时显示权威的**总 TPM**；`--by model` 显示各模型 TPM；`--by agent` 和 `--by project` 显示从可见窗口左边界开始的累计 Token 增长。分组视图可用 `--legend values` 显示无标记的紧凑列表，列出各可见项及其最新显示值。紧凑 Monitor 排名只用排名旁的箭头表示真实名次变化，并用数值旁的 `↑`、`↓` 和 `—` 表示增长、下降和持平（`--ascii` 下为 `^`、`v` 和 `=`）；由于 Monitor 中每个序列都持续活跃，因此不显示活动点。初始基线不显示标记，之后首次出现的序列只显示数值上升，不伪造排名箭头。分组 Monitor 默认保留 Top 3，其余合并到 `Other`。`--agent`、`--model` 与 `--project` 都是仅启动时生效的数据源筛选。按 `Ctrl-C` 退出；`r` 立即采样，Space 暂停/恢复，`v` 按图表 → 精简命令 → 完整命令 → Markdown 数据表 → JSON 数据 → 图表循环。精简命令省略默认参数，完整命令显式列出所有生效设置。图表视图可用 `m` 调整但不可复制；其余视图可用 `y` 复制但不可调整。数据表和 JSON 都只序列化当前显示的桶（包括分组、Top N 与 `Other`），不暴露原始计数器。`h` 隐藏或恢复仅当前会话的控制栏以归还图表行数，`m` 仅可从图表打开固定两行的运行时调整面板。快捷页可调整窗口、间隔、分组、Top、主题和样式，不会重新查询或丢失已保留历史；按 `a` 切换到高级页调整图例，`y` 会复制候选命令。启动时的 `--model` 筛选会保持不变，不作为运行时控制。调整引导始终可见，关闭面板后会恢复此前的控制栏偏好。Monitor 横轴使用 `HH:MM` 标签。可用 `--theme` 和 `--style` 指定初始外观；真实观测历史在启动时尚不存在；要立即比较样式请使用 `monitor --demo`。Demo Monitor 数据是确定性的，启动即有波动的内存历史，绝不调用 `ccusage`。

观测 TPM 不等同于 QPM，也不等同于 API 速率限制 TPM；当前没有 QPM 指标。未来若加入外部 QPM，将统计逻辑请求，绝不会从 Token 或重试次数推断请求数。Monitor 的 `style=ranking` 是进程内观测窗口的当前值紧凑视图，不是累计历史数据的 `ranking` 子命令：总量与模型模式显示当前观测 TPM，Agent 与项目模式显示当前可见窗口内的 Token 增长。Monitor 不宣称提供历史逐分钟数据、任意日期范围的小时分布或启动前的滚动窗口。采样间隙、查询错误和计数器回退不会被伪装成零流量。

## Dashboard

```bash
# 默认填满的 2×2 总览；Monitor 默认按模型显示 TPM
ccuv dashboard

# 选择任意支持的子图和启动网格
ccuv dashboard --pane "timeline --period 7d" --pane "stack" \
  --pane "ranking --by agent" --pane "monitor --by model --top 5" --grid 2x2

# 设置 Dashboard 拥有的 Historical 刷新与 Monitor 采样间隔
ccuv dashboard --refresh-interval 30 --sampling-interval 5

# 选择页眉样式、摘要粒度及其独立摘要刷新间隔
ccuv dashboard --header-style panel --header-summary quarter --header-interval 90
```

`dashboard` 使用一个终端输入循环和合成器；每个 Pane 保留最近结果、失败状态，Monitor Pane 还保留自己的内存观测历史。默认 Dashboard 是填满的 2×2 总览，包含 Timeline、Stack、Ranking，以及按模型分组的 Monitor。自动生成的 Monitor 等同于 `monitor --by model`；独立运行 `monitor` 或显式指定 `--pane "monitor"` 时仍显示权威的总体 TPM。`--pane` 可重复，值是以 `timeline`、`calendar`、`stack`、`ranking` 或 `monitor` 开头的图表片段；片段内禁止 Host、进程和生命周期选项。Dashboard 拥有调度：`--refresh-interval` 控制 Historical Pane 刷新，`--sampling-interval` 控制 Monitor Pane 采样。`--grid ROWSxCOLUMNS` 设置启动网格，`auto` 最多使用两列。

Dashboard 页眉与子图摘要彼此独立。`--header-style` 支持 `hidden`、`compact`、`banner` 和默认的 `panel`。`--header-summary` 独立选择 `day`、`month`、`quarter`、`year` 或 `none`（默认 `day`）；`none` 保留标题与更新时间但省略详情，`hidden` 隐藏整个页眉。冷切换粒度时会立即显示完整的本地化结构和 `??` 占位，只有已接受的数据才会替换它。页眉使用未筛选的全部 Agent 总量，默认每 60 秒独立刷新；失败或过期结果不会推进成功更新时间。Dashboard 的 `--theme` 只控制外壳、大标题、页眉摘要、占位和分隔，子图保留各自独立的 `--theme`。Dashboard 的 `--style` 将外壳结构统一为 `minimal`、默认的 `split`、`framed` 或 `accent`，不会改变子图图表样式或 Header Style。按 `s` 从第一个子图开始调整，或点击任意子图直接调整；浏览时 `Tab` 不执行操作，子图调整时循环切换子图。

页脚默认保持三行：上下文相关的子图命令、全局调度/布局命令、全局外观命令。浏览状态下 `h` 可隐藏或恢复仅当前会话的页脚，并将三行归还给子图网格；调整、布局编辑和添加子图时始终显示引导。浏览状态下 `Tab` 不执行操作；调整状态下 `Tab` 循环切换目标。每次调整默认显示**快捷**设置；按 `a` 在快捷和**高级**设置之间切换，只有当前页面列出的按键会生效。Timeline/Stack 的星期标签（`k`）和各子图较少使用的控件位于高级页面，因此 `l` 仍可用于调整图例。`r` 立即刷新全部子图，并更积极地刷新当前页眉摘要所需区间；Space 全局暂停/恢复自动调度，暂停时仍可立即刷新；`v` 切换子图命令详情；`a` 添加子图；`z` 编辑当前会话布局；`w` 切换页眉；浏览模式 `u` 按 `day → month → quarter → year → none` 循环；`d` 切换分隔线；`f` 切换持续子图边框；调整状态下 `x` 删除目标子图（至少保留一个）。浏览状态下按 `y` 会复制一条全局 `dashboard` 命令，包含当前有序子图、布局、调度、页眉、分隔线、边框、主题、Demo 与终端显示设置；调整状态下的 `y` 仅复制当前子图。复制历史子图会用规范的 `--interval` 带上该子图当前刷新间隔，即使 Dashboard 当前处于暂停状态；复制 Monitor 子图同样保留其 `--interval`。`Ctrl-C` 会还原终端并取消活动查询。

Monitor 在独立命令和 Dashboard 中共用带留白且稳定的 y 轴。数据越界时上界立即扩大，持续处于低区间后才缩小，因此小幅变化会表现为折线移动，而不是坐标轴不断移动。指标语义不变：总体与模型仍是观测 TPM，Agent 与项目仍是在可见窗口内的 Token 累计增长。

Dashboard 子图之间不共享已经完成的数据。可执行命令字符串、参数元组和超时完全相同且执行时间重叠的调用会共用一个运行中的子进程，随后每个子图获得独立解码副本；其他调用不会合并。只有独立页眉保留当前进程内、未筛选的每日覆盖缓存：覆盖充分时切换粒度立即渲染；切换到更宽但未覆盖的粒度时只查询页眉数据，并在结果接收前以 `?` 表示未知详情；成功接收的区间会权威替换缓存中的对应记录。失败、取消或过期结果不会改变已接收的页眉数据和更新时间。

## 历史图表生命周期

历史图表默认持续刷新，间隔为 10 秒：

```bash
ccuv timeline                # 每 10 秒刷新
ccuv timeline --interval 20  # 自定义刷新间隔
ccuv timeline --no-watch     # 绘制一个完整交互式画面后退出
```

最小间隔为两秒。`--interval` 不能与 `--no-watch` 同时使用。等待从上一次刷新完成后开始，因此不同刷新不会重叠。持续运行的历史图表会在终端最后一行显示精简快捷键提醒；Demo 模式还会显示数据档位按键。快捷键：

- `Ctrl-C` — 退出，并取消此进程拥有的 `ccusage` 子进程。
- `r` — 立即刷新；如果正在刷新，最多再排队一次。
- `h` — 隐藏或恢复仅当前会话的控制栏，归还一行给图表；调整引导始终可见。
- `Space` — 暂停或恢复自动刷新；暂停时仍可手动刷新。
- `v` — 按图表 → 精简命令 → 完整命令 → Markdown 数据表 → JSON 数据 → 图表循环；页脚会提示下一个视图。
- `y` — 图表中不可用；在对应文本视图复制精简命令、完整命令、完整 Markdown 表或完整 JSON。
- `m` — 仅图表中可用，用于调整当前历史视图；滚动范围仅提供 7、14、30、365 天。调整默认显示**快捷**设置；按 `a` 查看**高级**设置，其中 Timeline/Stack 可通过 `k` 调整星期标签。
- `s`、`d`、`l` — Watch Demo 时切换合成数据量级（其中 `d` 选择 medium）。

Watch 的数据表和 JSON 视图只序列化图表就绪的筛选后、聚合后数据模型：显示的日期桶、序列/组成、Top N 与 `Other`，绝不显示聚合前的提供方记录。精简命令省略默认参数；完整命令用于审计，包含本地可执行文件、超时和已选项目路径设置。Watch 运行时使用完整可用终端高度，刷新重绘不追加尾随换行，因此不会在每次刷新时向上滚屏。状态固定在第一行，快捷键提醒固定在最后一行，警告提示带有警告符号和固定语义前景色，显示在快捷键上方。刷新期间保留原有状态文字，只在末尾追加低强调的“刷新中”，并且只更新第一行；按下 Space 也会立即更新该行，包括查询仍在执行时。新结果到达后才重绘当前正文；终端尺寸变化也会强制完整重绘。退出时只写入一个最终换行，让 Shell Prompt 从新行开始。一次性渲染则会为后续 Shell Prompt 预留一行，并继续把提示放在图表上方。刷新期间或后续出错时保留上一张成功图表。无数据和终端过小状态仍会存活，等待后续刷新。`--period 14d` 这样的相对时间窗口会在所选自然日时区跨过午夜时前移；显式指定边界的范围保持不变。`Ctrl-C` 会退出、恢复终端输入模式，且不打印 traceback。

可以独立运行多个 Watch 进程。程序没有全局锁、Daemon、PID 文件、共享缓存或跨进程状态；每个实例只管理自己的子进程。并发实例也会独立运行 `ccusage` 扫描，因此 CPU、磁盘和内存开销会叠加。

### 暂缓小时与滚动历史视图

当前 `ccusage 20.0.20` JSON 无法准确支持小时历史：每日数据只有日期，Session 只有聚合总量而非分时数据，Claude blocks 是五小时计费窗口，而且 Claude/Codex 没有统一的请求次数字段。上游小时功能 PR [#724](https://github.com/ccusage/ccusage/pull/724) 已关闭且未合并，原 `blocks --live` 监控也已在 [#782](https://github.com/ccusage/ccusage/pull/782) 中删除。因此，ccuv 不会宣称提供准确的滚动 24 小时峰值、小时使用习惯或调用量，也不会通过读取 Agent 原始日志、采样写入历史文件、运行 Collector 或创建用量数据库来绕过限制。准确小时视图需等待上游提供受支持的小时 JSON 契约。

## Demo 模式

```bash
ccuv timeline --demo         # medium
ccuv timeline --demo small
ccuv timeline --demo medium
ccuv timeline --demo large
```

生成的记录是确定性的。三个档位只改变数值量级，不改变日期、形状或标识；数据涵盖零值日期、峰值、单位边界、跨 Agent 同名项目、Token 残差和 Top 溢出。Demo 模式从不调用 `ccusage`，也不写入用量记录。

### 图表样式

Theme 负责语义前景色，Style 负责图表形态。使用 `--theme` 和 `--style` 指定初始外观；TUI 运行期间可按 `m` 基于已保留快照调整受支持的设置，不会因此发起新查询。

Dashboard 浏览模式有意只保留一行控制栏：`r` 刷新全部、`s`/点击调整子图、`g` 全局调整、`h` 隐藏/显示控制栏、`y` 复制仪表盘、Space 暂停/继续调度。Dashboard 不再提供详情或子图命令显示。来自子图的数据和能力警告会去重后显示在控制栏正上方的全局警告区，不会挤占紧凑子图单元格的内容。子图和全局调整均先进入**快捷设置**，`a` 切换到**高级设置**。全局快捷设置包含主题、样式、页眉、摘要和布局；全局高级设置使用 `+` 添加子图，并提供 `x` 删除、`[`/`]` 排序和 `Tab` 选择子图。复制 Dashboard 会保留外壳 Theme/Style 与每个子图各自独立的 Theme/Style。

样式按子命令定义：Timeline 支持 `linear`、`step`、`no-line`、`points`、`line-points`、`stem`、`area`。`no-line` 不连线但保留各系列不同的标记；`points` 使用统一实心点且不连线；`line-points` 使用统一实心点和线性连线。Monitor 支持 `bars`、`line`、`step`、`points`、`line-points`、`ranking`；两个统一点样式与 Timeline 的无线和线性连线语义相同。Calendar 支持 `relative`、`absolute`；Stack 支持 `stacked`、`stacked-pattern`、`grouped`、`grouped-thin`、`normalized`；Ranking 支持 `bar`、`dot`、`dots`。`--ascii` 独立于 Theme 和 Style，只改变字符。

## 语言与终端行为

使用 `--lang en` 或 `--lang zh`。未指定时，Python 系统 Locale 中的 `zh_CN`、`zh_SG` 或 `Hans` 选择简体中文；繁体中文 Locale 与其他语言回退为英文。

所有子命令都支持 `--theme classic|vivid|contrast|dracula|catppuccin|solarized|gruvbox|nord|github|mono|no-color`，默认为 `classic`。Dracula、Catppuccin、Solarized、Gruvbox、Nord 与 GitHub 是对成熟主题家族的 ANSI-256 精选适配，并非编辑器主题的逐值复刻。GitHub 主题为 Calendar 提供类似贡献图的四档绿色，并为所有命令提供完整语义色。主题只设置前景色，覆盖 Timeline 序列与“其他”、Calendar 强度、Stack 构成、Ranking 标记和诊断高亮。程序不推断终端品牌或明暗背景，因此继续继承终端背景。Timeline 会联合分配分类颜色并配合不同标记；Stack 使用冷暖混合分类色和不同构成字符，因此不会只依赖颜色区分。Calendar 使用有序的四档配色，而字符密度（`░▒▓█`，设置 `--ascii` 时为 `.oO#`）始终是从低到高的权威强度编码。

使用 `--theme no-color` 可显式且可复现地禁用 ANSI 样式；程序不解释 `NO_COLOR`。显式 `--ascii` 不能与任何显式 `--theme` 同时使用，包括 `classic` 和 `no-color`；省略 `--theme` 时，隐式默认主题仍然有效。`TERM=dumb` 必须显式提供 `--ascii`，程序绝不会自动启用 ASCII。最小终端尺寸为：

| 子命令 | 最小尺寸 |
| --- | --- |
| `timeline` | 58×16 |
| `calendar` | 58×16 |
| `stack` | 58×16 |
| `ranking` | 58×16 |

## 推荐 Alias

```bash
alias cct='ccuv timeline'
alias ccm='ccuv timeline --by model --period 30d'
alias ccs='ccuv stack --period 30d --cache split'
alias ccp='ccuv ranking --by project --period 30d'
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
