# 使用指南

[English](usage.md)

<!-- guide:overview -->

## 概览与前置条件

本文是 `ccusage-viz` 及其短命令 `ccuv` 的操作参考。两个已安装命令等价；也可通过模块运行：

```bash
ccuv --help
ccusage-viz --help
python -m ccusage_viz --help
```

请按 [README](../README.zh-CN.md) 安装本程序。要查询真实数据，需另行安装
[`ccusage`](https://github.com/ryoppippi/ccusage) 并使其位于 `PATH`；
`ccusage-viz` 不内置它。若其命令名或位置不同，请使用 `--ccusage-bin`。

图表面向交互式终端。探索时可使用可重复的确定性示例数据：`--demo` 等同于
`--demo medium`，也可选择 `--demo small` 或 `--demo large`。Demo 模式不会运行
`ccusage`，也不会保存数据。

`timeline` 是隐式命令。以下写法等价：

```bash
ccuv
ccuv timeline
ccuv --demo
ccuv --lang zh --demo
```

安装与视觉概览请参阅 README。实现和维护者背景请参阅[架构文档](architecture.zh-CN.md)，
不要将其当作命令参考。

<!-- guide:command-map -->

## 快速开始与命令地图

首次体验可从 Demo 数据开始：

```bash
ccuv timeline --demo
ccuv calendar --demo
ccuv stack --demo --cache split
ccuv ranking --demo --by project
ccuv monitor --demo --by model
ccuv dashboard wide --demo
```

| 路由 | 数据模型 | 终端组成 | 主要问题 |
| --- | --- | --- | --- |
| `timeline` | 历史日期范围 | 单个独立图表 | Token 使用量随时间如何变化？ |
| `calendar` | 历史日期范围 | 单个独立图表 | 哪些日期活跃、强度如何？ |
| `stack` | 历史日期范围 | 单个独立图表 | 输入、输出和缓存 Token 的构成如何？ |
| `ranking` | 历史日期范围 | 单个独立图表 | 哪个 Agent、模型或项目使用 Token 最多？ |
| `monitor` | 滚动观测窗口 | 单个独立图表 | 当前进程观测到了什么吞吐量？ |
| `dashboard` | Host 全局节奏与独立 Pane | 多 Pane Dashboard | 多个已配置图表如何并排比较？ |

历史路由查询日期范围。`monitor` 则在当前进程运行期间重复采集累计快照；它不能重建
启动前的吞吐历史。独立图表占满终端。Dashboard 是单独的多 Pane Host，复用相同的图表组件，
而不是独立图表的包装器。

<!-- guide:shared-standalone-options -->

## 独立图表共用 CLI 参数

下列参数按表中所示适用于独立图表。**默认值**是解析器默认值；命令专属默认值在后续表格中列出。

### 呈现与进程参数

| 参数 | 可接受值 | 默认值 | 适用范围 | 行为 |
| --- | --- | --- | --- | --- |
| `--demo [SIZE]` | `small`、`medium`、`large` | 关闭；裸参数为 `medium` | 全部 | 使用确定性进程内数据，不调用 `ccusage`。 |
| `--lang LANG` | `en`、`zh` | 系统检测语言 | 全部 | 选择英文或简体中文消息/帮助；可置于命令之前。 |
| `--ccusage-bin PATH` | 命令名或路径 | `ccusage` | 全部 | 实时查询所用的可执行文件。 |
| `--query-timeout SECONDS` | 正且有限的数字 | `30` | 全部 | 实时查询最长时间。该高级受支持参数刻意不显示在常规 `--help` 中。 |
| `--ascii` | 标志 | 关闭 | 全部 | 使用 ASCII 兼容渲染。不能和显式提供的 `--theme` 同用。 |
| `--theme THEME` | `classic`、`vivid`、`contrast`、`dracula`、`catppuccin`、`solarized`、`gruvbox`、`nord`、`github`、`mono`、`no-color` | `classic` | 全部 | 图表配色；`no-color` 关闭图表颜色。 |
| `--density DENSITY` | `minimal`、`compact`、`full` | `full` | 全部独立图表 | 图表细节与装饰的数量。 |
| `--style STYLE` | 命令专属，见图表表格 | 命令专属 | 全部 | 所选图表的渲染样式。 |
| `--legend POSITION` | Timeline：`below-title`、`inside`、`hidden`；Stack：`below-title`、`hidden`；Monitor：`below-title`、`inside`、`hidden`、`values` | `below-title` | Timeline、Stack、Monitor | 图例位置/内容。 |

`--ascii --theme classic` 与 `--ascii --theme no-color` 都无效：冲突由**显式**指定主题导致。
不指定 `--theme` 时使用 `--ascii` 是有效的。

### 历史范围、筛选与调度

| 参数 | 可接受值 | 默认值 | 适用范围 | 行为 |
| --- | --- | --- | --- | --- |
| `--period PERIOD` | 正整数加 `d`、`mo`、`q` 或 `y`，如 `14d`、`13mo`、`1q` | Timeline/Stack/Ranking：`14d`；Calendar：`365d` | 历史路由 | 以运行 ccuv 的机器本地当天结束的滚动范围。 |
| `--since YYYY-MM-DD` | ISO 日期 | 未设置 | 历史路由 | 固定或开放范围的起始日期。 |
| `--until YYYY-MM-DD` | ISO 日期 | 未设置 | 历史路由 | 固定范围的结束日期；需要 `--since`。 |
| `--agent VALUE` | 可重复文本 | 无 | 历史路由与 Monitor | 按完整 Agent 值筛选。 |
| `--model VALUE` | 可重复文本 | 无 | 历史路由与 Monitor | 按完整模型值筛选。 |
| `--project VALUE` | 可重复文本 | 无 | 历史路由与 Monitor | 按完整安全项目标签筛选。 |
| `--project-aggregation MODE` | `name`、`exact`；默认 `name` | `name` | `--by project` 的 Timeline、Ranking、Monitor | 项目呈现模式；不会放宽精确项目筛选。 |
| `--interval SECONDS` | 有限数字；历史图表至少 `2` | `10` | 历史路由 | 监听时的刷新节奏。 |
| `--no-watch` | 标志 | 关闭 | 历史路由 | 仅查询一次后退出，不持续监听。 |

同一维度重复筛选值表示匹配其中任一个值，不同维度之间同时生效。例如，以下表示
**Agent A 或 B**，使用**模型 X**，且属于**项目 one 或 two**：

```bash
ccuv timeline --agent A --agent B --model X --project one --project two
```

所有 Agent、模型和项目选择器都是**完整值、不区分大小写的精确匹配**。ccusage-viz
不会回退为前缀、子串、包含匹配或其他隐式匹配：`--agent "CLAUDE CODE"` 可匹配
`Claude Code`，但 `--agent claude` 不会匹配；`--model` 和 `--project` 同样遵循此规则。

项目身份以 Agent 为作用域；不同 Agent 出现同名项目时，请使用 TUI 显示的安全消歧项目标签。
Claude 的不透明上游标识绝不会被还原为文件系统路径。Timeline 和 Ranking 只将其视为连字符分隔的
token，并在完整筛选后项目池的每个 token 前缀树分支中，消除可证明共享的最深前缀。任何 token 都
没有特殊的路径语义；缩短只受非空且无歧义后缀约束。无法证明共享前缀的 ID 展示完整不透明标识符。
不同的独立发现范围可能显示不同标签。Timeline 和 Ranking 会在 Top 或 Other 选择前记录已验证的
最短后缀；后续范围过窄的 Monitor 采样可以复用该进程内标签，但绝不会更新它。
整个产品中的模型名均不区分大小写：筛选、聚合、Monitor 和显示都会使用小写模型名。

<!-- guide:historical-rules -->

## 历史范围、刷新与呈现规则

### 范围与刷新

`--period` 选择滚动范围。`14d`、`3mo`、`1q`、`1y` 有效；`0d`、`2w`、`month` 无效。
若显式 `--since` 没有 `--until`，命令启动时的当天就是结束日期。两个日期同时提供时范围固定；
相对范围可随本地自然日推进。

下列组合会被拒绝：

| 无效组合 | 原因 |
| --- | --- |
| `--period` 与 `--since` 或 `--until` | 请选择相对范围或显式日期，不能同时使用。 |
| `--until` 没有 `--since` | 结束日期需要起始日期。 |
| `--since` 晚于 `--until` | 日期顺序无效。 |
| 未来的 `--until` | 历史数据不能在未来结束。 |
| `--interval` 与 `--no-watch` | 单次运行没有调度间隔。 |
| 历史 `--interval` 小于 `2` | 历史监听最小间隔是两秒。 |

历史图表默认持续监听。运行时按 `Space` 暂停/恢复，或用 `--no-watch` 只查询一次。

### 密度、样式与分组

- `minimal` 提供最紧凑的图表呈现；`compact` 适合 Pane；`full` 是独立图表默认值。
- Timeline 样式为 `linear`、`step`、`no-line`、`points`、`line-points`、`stem`、`area`。
  分组 Timeline（`--by ...`）不能使用 `area`。
- Calendar 样式为 `relative` 和 `grid`。
- Stack 样式为 `stacked`、`stacked-pattern`、`grouped`、`grouped-thin`、`normalized`。
- Ranking 样式为 `bar`、`dot`、`dots`。
- Monitor 样式为 `bars`、`line`、`step`、`points`、`line-points`、`ranking`、`list`。
  分组 Monitor 不能使用 `bars`。

筛选发生在分组和 Top 选择之前。Timeline 和 Monitor 的 `--top` 需要 `--by` 维度，选择分组而
没有显式 Top 时默认 `3`。Ranking 始终分组（默认 `--by project`），默认 `--top 10`。Top 必须是
正整数。`--other show|hide` 控制 Timeline 和 Ranking 是否将 Top 以外的分组显示为 **Other**。

### 项目聚合与项目归因覆盖范围

Timeline、Ranking 和 Monitor 按项目分组时，`--project-aggregation name` 是默认值。它只会合并
无歧义的 Claude–Codex 配对，绝不会合并同一 Agent 内的项目。先比较安全的末级名称；当 Codex
存在重名末级目录时，可以仅用私有父级后缀选择保守的一对一配对。这些后缀只是分组键，不会显示为
标签，也不代表重建出的路径。简洁的合并标签仅用于呈现，不代表这些记录来自同一个工作目录。筛选
始终先针对精确来源项目身份执行，再应用这一呈现聚合。

使用 `--project-aggregation exact` 可分别保留每个上游 `(agent, project)` 来源身份。Exact 模式图表
始终在可见项目名称前加上 Agent，例如 `claude · app`；数据表和 JSON 将相同值作为
`display_project`，并另外提供 `agent` 字段。跨 Agent 的 Name 分组不会人为生成一个单独的 Agent 值。

所有项目数据视图都包含 `display_project` 和 `merge_group`。`display_project` 是图表当前实际显示的
标签。相同且非空的 `merge_group` 表示来源项目会相加为同一个跨 Agent Name 分组；空值表示该行是
Exact 或其他未合并项目。编号从 `0` 开始，只在当前输出内按确定性顺序有效，并非跨范围、筛选或 Top
选择的持久项目标识。项目 Ranking 还会将一个 Name 分组展开为安全的来源行，这些行共享该图表项目的
`rank`。Other 仍为聚合行，不会虚构来源明细。

下方兼容性基线在 macOS 上使用 **ccusage 20.0.23** 完成验证。Token 总量指 ccusage 在统一
用量数据中报告某个 Agent；历史项目归因还要求每条记录具有稳定、真实的项目身份。

| Agent | Token 总量 | 历史项目归因 | Agent 版本 | ccusage 版本 | 依据 |
| --- | --- | --- | --- | --- | --- |
| Claude Code | 已验证 | 已验证 | 2.1.278 | 20.0.23 | `claude daily --instances --json` 提供项目记录。 |
| Codex | 已验证 | 已验证 | 0.139.0 | 20.0.23 | 优先使用 ccusage 的 `cwd`/项目字段；缺失时仅读取匹配本地 `session_meta.cwd` 元数据。 |
| OpenCode | 已验证 | 不支持（已验证） | 1.17.20 | 20.0.23 | 真实 session 输出没有项目身份字段。 |
| Antigravity | 已验证 | 不支持（已验证） | 2.0.10 | 20.0.23 | 真实 `projectPath` 都是通用常量 `Antigravity`，不是工作目录。 |

对于 Codex session，ccusage 的 `cwd`/项目字段具有最高优先级。当当前输出仅有 session ID 与存储
`directory` 时，ccusage-viz 仅读取匹配本地 session 的 `session_meta.cwd`；`directory` 绝不作为项目
身份。若两者都无法提供 cwd，用量仍会显示为**Unassigned Codex**，并以通用提示标记项目归因不完整。不会
分析、存储或显示对话、工具或消息内容。

历史项目请求若在所选范围内发现 OpenCode、Antigravity 或其他不支持的 Agent，会显示一条列出其名称的
警告。由于 ccusage-viz 不会虚构项目记录，这些 Agent 的项目用量可能缺失或不完整。该警告不改变
项目总量、覆盖范围或筛选行为，也不适用于 Monitor 独立的累计项目行为。

只有在同一改动包含脱敏的非空真实数据 fixture、parser/provider 覆盖、项目 Ranking 端到端验证、
与统一 daily Token 总量的核对，以及精确的 Agent 与 ccusage 测试版本时，才可将该 Agent 标为**已验证**。

<!-- guide:standalone-charts -->

## 独立图表参考

### Timeline

```bash
ccuv timeline --period 30d --by model --top 5 --style line-points
```

| 参数 | 值/默认值 | 含义 |
| --- | --- | --- |
| `--by` | `agent`、`model`、`project`；默认总计 | 分组时间序列。 |
| `--top` | 正整数；选择 `--by` 后默认 `3` | 显示的分组数量；需要 `--by`。 |
| `--other` | `show`（默认）、`hide` | 显示/隐藏 Top 选择后的剩余值。 |
| `--granularity` | `day`（默认）、`month`、`quarter`、`year` | 历史范围的分桶粒度。 |
| `--weekdays` | `show`（默认）、`hide` | 在适用位置显示/隐藏星期标签。 |
| `--legend` | `below-title`（默认）、`inside`、`hidden` | 图例位置。 |
| `--project-aggregation` | `name`（默认）、`exact`；仅用于 `--by project` | 使用安全的跨 Agent 同名呈现，或保留每个精确来源。 |
| `--style` | Timeline 样式 | 分组时 `area` 不可用。 |

### Calendar

```bash
ccuv calendar --period 1y --style grid
```

| 参数 | 值/默认值 | 含义 |
| --- | --- | --- |
| `--style` | `relative`（默认）、`grid` | 日历热力图呈现方式。 |
| 历史共用参数 | 见上文 | 范围、筛选、语言/进程/呈现与监听行为。 |

Calendar 没有分组、Top、Other、粒度、星期标签或图例参数。

### Stack

```bash
ccuv stack --period 30d --granularity month --cache split
```

| 参数 | 值/默认值 | 含义 |
| --- | --- | --- |
| `--cache` | `combined`（默认）、`split` | 合并缓存 Token，或分别显示缓存读取和缓存创建。 |
| `--granularity` | `day`（默认）、`month`、`quarter`、`year` | 历史范围的分桶粒度。 |
| `--weekdays` | `show`（默认）、`hide` | 在适用位置显示/隐藏星期标签。 |
| `--legend` | `below-title`（默认）、`hidden` | 图例可见性。 |
| `--style` | Stack 样式 | 选择堆叠、分组或归一化渲染。 |

例如：

```bash
ccuv stack --demo --cache split --style stacked-pattern
```

### Ranking

```bash
ccuv ranking --period 30d --by project --top 15 --other hide --style dots
```

| 参数 | 值/默认值 | 含义 |
| --- | --- | --- |
| `--by` | `project`（默认）、`agent`、`model` | 排名维度。 |
| `--top` | 正整数；默认 `10` | 排名值数量。 |
| `--other` | `show`（默认）、`hide` | 显示/隐藏 Top 以外的值。 |
| `--project-aggregation` | `name`（默认）、`exact`；仅用于 `--by project` | 使用安全的跨 Agent 同名呈现，或保留每个精确来源。 |
| `--style` | `bar`（默认）、`dot`、`dots` | 排名呈现方式。 |

### Monitor

```bash
ccuv monitor --window 30m --by model --top 5 --style ranking
```

Monitor 在本次运行期间从重复累计快照观测吞吐量。第一个被接受的快照建立基线；观测历史仅属于
当前进程，进程退出后即消失。时间线样式会在本次运行的启动时刻仍位于可见滚动窗口内时标记它，
明确表示此前时间未被观测，而不是零用量。所有密度都会显示该线；空间允许时，full 和 compact
密度会显示标签。ranking 和 list 样式不显示这个时间线标记。

| 参数 | 值/默认值 | 含义 |
| --- | --- | --- |
| `--window` | `Nm` 或 `Nh`，范围 `5m` 至 `24h`；默认 `1h` | 滚动观测窗口。 |
| `--interval` | 真实数据至少 `5` 秒，Demo 至少 `1` 秒 | 采样节奏；未显式提供时，真实数据默认 `15` 秒，Demo 默认 `1` 秒。 |
| `--by` | `agent`、`model`、`project`；默认总计 | 分组观测吞吐量。 |
| `--top` | 正整数；选择 `--by` 后默认 `3` | 显示的分组数量；需要 `--by`。 |
| `--legend` | `below-title`（默认）、`inside`、`hidden`、`values` | 图例模式。 |
| `--style` | Monitor 样式 | 分组 Monitor 不能使用 `bars`；`list` 包含进程/条目详情。 |

`--no-watch` 为兼容性被解析器接受，但在常规帮助中隐藏，并会被 Monitor 拒绝：Monitor 始终连续运行。
总计模式报告总 Token/分钟。分组 `model` 报告模型吞吐量；分组 Agent 和项目视图使用观测到的
最新成对 Token 增长。

`cumulative-bars` 是独立的按自然日 Token 视图：显示本地自然小时（或半小时）内累计的增量，
而不是 TPM。按 `w` 在默认的**今天**和**昨天**之间切换，按 `g` 在**每小时**和**30 分钟**
桶之间切换。它沿用其他 Monitor 样式的分组、Top/Other 和稳定系列颜色。当前未结束的桶和
启动后的残缺桶会标为部分覆盖；采样间隔及其他没有可信观测的数据以暗色/斜线占位，而不是零。
已观测到的零值仍显示为零值桶。为支持该视图，Monitor 最多保留 50 小时的分钟级聚合；
不会根据仅按日期提供的历史数据重建日内历史。`ranking` 和 `list` 已经描述当前观测，
因此不显示 `w`。

<!-- guide:dashboard-startup -->

## Dashboard 启动与组合

Dashboard 是多 Pane Host。裸调用启动 `wide` 预设：

```bash
ccuv dashboard
ccuv dashboard wide
ccuv dashboard wide --demo
```

### 预设

| 预设 | Pane 组成 | 网格/布局 | Dashboard 样式 |
| --- | --- | --- | --- |
| `wide` | Timeline、Stack、Ranking、按模型分组的 Monitor | `2x2` | `framed` |
| `spotlight-wide` | Timeline、Stack、Ranking | 带 `spotlight-wide` 的 `2x2` | `framed` |
| `spotlight-wide2` | Timeline、Stack、Ranking、按模型分组的 Monitor | 带 `spotlight-wide2` 的 `2x2` | `framed` |
| `narrow` | 14 天 Timeline、项目 Ranking、模型 Monitor | `3x1` | `framed` |
| `all` | 两个 Timeline、Calendar、Ranking、两个 Stack 与四个 Monitor 变体 | `5x2` | `split` |

默认 `wide` Pane 使用 `compact` 密度，并刻意采用不同图表主题/样式。`spotlight-wide` 让第一个 Pane
占据前导宽区域；`spotlight-wide2` 让前两个 Pane 占据连续的宽行。

预设是启动模板，不是 `--grid` 的取值。重复 `--pane` 会追加到预设 Pane 后；需要时 Host 会扩展预设
网格以容纳所有 Pane。

### 构造自定义 Dashboard

Pane 片段是一个安全引用的图表命令及图表参数：

```bash
ccuv dashboard \
  --pane 'timeline --period 30d --by model --top 5 --style line-points' \
  --pane 'ranking --by project --top 10 --style dots' \
  --pane 'monitor --window 1h --by model --style ranking' \
  --grid 2x2
```

使用命名布局时不要提供 `--grid`：

```bash
ccuv dashboard \
  --pane 'timeline --by model' \
  --pane 'stack --cache split' \
  --pane 'ranking --by project' \
  --layout spotlight-wide
```

支持的 `--layout` 值为 `auto`、`spotlight-wide`、`spotlight-wide2`。网格形式为
`ROWSxCOLUMNS`，必须有足够单元格容纳所有 Pane。

自定义 Pane 若未在片段中显式提供 `--density`，则默认 `compact` 密度。

### Dashboard Host 参数

| 参数 | 值/默认值 | Host 所有的行为 |
| --- | --- | --- |
| `--demo [SIZE]`、`--lang`、`--ccusage-bin`、`--query-timeout` | 与独立图表语义相同；裸 Demo 是 `medium`；timeout 默认 `30` | 所有 Pane 的 Provider/进程/输入配置；`--query-timeout` 是隐藏高级配置。 |
| `--ascii` | 关闭 | Host 和 Pane 的 ASCII 渲染；与显式 Pane `--theme` 冲突。 |
| `--theme THEME` | `classic` | Dashboard 外壳主题，区别于每个 Pane 的图表主题。 |
| `--grid ROWSxCOLUMNS` | 仅自定义构造 | 所选 Pane 数量的逻辑网格。 |
| `--layout NAME` | 仅自定义构造 | 命名布局；不能和预设或 `--grid` 同用。 |
| `--column-weight WEIGHT` | 重复正整数 | 隐藏的仅启动时高级逻辑列份额；数量必须匹配布局列数。 |
| `--row-weight WEIGHT` | 重复正整数 | 隐藏的仅启动时高级逻辑行份额；数量必须匹配布局行数。 |
| `--refresh-interval SECONDS` | `15`；预设可能提供自己的默认值 | Dashboard 全局历史刷新节奏；最小 `1`。 |
| `--sampling-interval SECONDS` | `15`；预设可能提供自己的默认值 | Dashboard 全局 Monitor 采样节奏；最小 `1`。 |
| `--header-style STYLE` | `hidden`、`compact`、`banner`、`panel`；默认 `panel` | Dashboard Header 呈现。 |
| `--header-summary SUMMARY` | `day`、`month`、`quarter`、`year`、`none`；默认 `day` | Header 汇总周期。 |
| `--header-interval SECONDS` | `60` | Header 刷新节奏；最小 `1`。 |
| `--style STYLE` | `minimal`、`split`、`framed`、`accent`；没有预设时默认 `split` | Dashboard 外壳/边框样式，不是图表样式。 |

权重必须为正，且数量必须匹配解析后逻辑行/列带数量。Host 序列化完整命令时会规范化等价份额。
运行时调整大小只修改会话内逻辑权重。

### Host 与 Pane 的配置归属

Dashboard Host 负责布局、外壳主题/样式、Header、输入循环和节奏。Pane 负责图表选择、范围/窗口、
分组、Top/Other、筛选、图表主题/样式/密度，以及图表专属配置。

Pane 片段只能包含图表命令（`timeline`、`calendar`、`stack`、`ranking` 或 `monitor`）与图表参数，
不得包含如下 Host/生命周期参数：

```text
--interval --no-watch --watch --ascii --demo --lang
--ccusage-bin --query-timeout --pane --grid --refresh-interval
--sampling-interval --header-style --header-summary --header-interval
--help --version -h
```

Dashboard Header 刻意运行未筛选、全 Agent 的聚合查询；它不会变成当前 Pane 筛选结果的汇总。
同样，Dashboard `--style` 控制外壳，Pane `--style` 控制图表。Dashboard 的采样节奏属于 Host，
因此 Monitor Pane 调整不会提供独立 Monitor 的 `i` 间隔控制。

<!-- guide:interactive-controls -->

## 交互控制与独立图表调整

### 独立图表通用控制

除非表中指定视图/模式限制，独立 TUI 运行时可使用以下控制：

| 按键 | 行为 |
| --- | --- |
| `Ctrl-C` | 退出。 |
| `r` | 仅在图表视图刷新历史查询或立即请求一个 Monitor 样本；非图表文字视图中无操作。 |
| `h` / `H` | 图表视图中显示/隐藏仅当前会话的控制栏；文字视图中小写 `h` 跳到首行，`H` 无操作。 |
| `e` | 非图表文字视图中跳到末行。 |
| `Up` / `Down` | 非图表文字视图中逐渲染行滚动。 |
| `v` | 依次切换图表、紧凑命令、完整命令、Markdown 表格、JSON，再回到图表。 |
| `y` | 从非图表文本视图复制当前命令/数据。 |
| `Space` | 仅在图表视图暂停/恢复调度；非图表文字视图中无操作。 |
| `m` | 仅在图表视图打开调整。 |
| `s` / `d` / `l` | 在支持的调整器中分别控制样式/密度/图例。 |

紧凑命令视图省略默认值和私有项目路径。完整命令视图包含实际生效的设置，包括私有项目路径、
选定的二进制路径和 query timeout。复制不等于持久化：程序不会自动写入配置。运行时调整仅在当前
进程存活；若要复用，请自行保存复制出的命令。滚动只改变可见视口；`y` 始终复制完整、未滚动的命令或数据载荷。

### 快捷键约定

调整快捷键以当前可见页面或 Dashboard 管理模式为作用域；控制栏始终展示当前按键含义。
小写键用于当前图表或页面中常用的直接操作。`t/T` 是唯一的方向性按键对：`t` 向前切换主题，
`T` 向后切换主题。

大写通常不表示“反向”。`A` 和 `P` 是低频的 Advanced 项目呈现控制，仅在按项目分组时出现：
`A` 切换项目聚合（`name`/`exact`），`P` 逐级显示更多安全的项目名称上下文。`f`、`l`、`o`、
`k` 和 `c` 即使位于 Advanced 页，仍用小写，因为它们是直接操作。

历史图表的 `p/P` 是兼容性例外：`p` 循环尾随周期，`P` 循环自然周期。二者是两组周期预设，
不是方向性按键对。它被刻意与 `t/T` 的规则分开说明，也不改变 Advanced 页中 `P` 的项目名称含义。

### 历史图表调整流程

Timeline、Calendar、Stack 和 Ranking 在图表视图按 `m` 打开调整器。调整器会预览修改；`a` 在
**Quick** 和 **Advanced** 页之间切换；`Enter`/换行提交当前候选配置；`Esc` 取消调整器。
仅视觉修改会立即更新预览；影响数据的修改会在提交后的配置刷新中使用。

调整模式在连续 **3 分钟**内没有键盘或鼠标交互时会自动结束。按 Enter、`Esc` 或发生该超时后，独立图表都会回到图表视图；Dashboard 则回到普通浏览模式，并将 Dashboard 主体和所有 Pane 都恢复为图表视图。已在调整器中生效的修改保留其正常关闭语义；打开的筛选草稿会像按 `Esc` 一样丢弃。Dashboard 的布局和 Pane 类型子选择器同样会取消并返回浏览模式。

| 图表 | Quick 页 | Advanced 页 |
| --- | --- | --- |
| Timeline | `p/P` 范围；`g` 粒度；`b` 分组；`+/-` Top；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选；`o` Other；按项目分组时 `A` 项目聚合和 `P` 项目名称上下文；`l` 图例；`k` 星期标签 |
| Calendar | `p/P` 范围；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选 |
| Stack | `p/P` 范围；`g` 粒度；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选；`c` 缓存模式；`l` 图例；`k` 星期标签 |
| Ranking | `p/P` 范围；`b` 分组；`+/-` Top；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选；`o` Other；按项目分组时 `A` 项目聚合和 `P` 项目名称上下文 |
| Monitor | 时间线样式：`w` 窗口；`i` 采样间隔；`b` 分组；`+/-` Top；`d` 密度；`t/T` 主题；`s` 样式。`cumulative-bars`：`w` 今天/昨天；`g` 每小时/30 分钟；`b` 分组；`+/-` Top；`d` 密度；`t/T` 主题；`s` 样式。ranking/list 不显示 `w`。 | `f` 筛选；按项目分组时 `A` 项目聚合和 `P` 项目名称上下文；`l` 图例 |

`p` 循环尾随预设（`7d`、`14d`、`30d`、`365d`）；`P` 循环自然周期预设（`1mo`、`1q`、`1y`）。
二者都不会修改固定的显式日期范围。分组/样式变化会维持兼容样式；例如 Timeline 改为分组时，
`area` 会替换为兼容样式。

### 候选数据查询期间的显示

当控制项已切换到一个事实尚不可用的候选配置时，受影响图表的标题会立即附加低调的 `查询中`。
控制状态会立即生效；该标记用于解释这一刻刻意不完整的渲染。标记只属于受影响的图表，不会出现在
Dashboard 标题或其他 Pane。已接受配置的普通后台刷新可以显示 `刷新中`，但不会显示 `查询中`。

| 控制项变化 | 过渡期间的图表显示 |
| --- | --- |
| 历史图表的范围、筛选或分组 | 立即显示候选标题与汇总。旧图会隐藏，因为其日期、范围或排名不是候选配置的事实；匹配查询完成前，不可用数值以 `??` 显示。 |
| Timeline/Stack 粒度 | 立即重投影已接受的日记录。若只缺显示范围外的比较覆盖，图和当前值保持可见；仅比较值显示 `??`，并显示 `查询中`。 |
| 历史图表视觉控制 | 立即重绘或重投影已接受事实；不显示 `查询中`。 |
| Monitor 分组或筛选 | Pane 进入安全的空采样视图并显示 `查询中`；不会把此前观测值重新标记为候选分组/筛选的结果。 |
| Monitor 窗口、Top、间隔、分布日期/粒度或视觉控制 | 立即重投影或重绘保留的观测值；不显示 `查询中`。 |

因此，`??` 表示该显示事实尚未针对当前候选配置验证。当匹配结果被接受后，标记和未知值会一起消失。
若补充 comparison 查询失败，会保留已有失败提示和 `??`，但不再标记为 `查询中`。

### 筛选编辑器

Advanced 页的 `f` 编辑器会先起草筛选，再提交：

| 按键 | 行为 |
| --- | --- |
| `h` / `Left` | 上一个维度 |
| `l` / `Right` / `Tab` | 下一个维度 |
| `k` / `Up` | 上一个值 |
| `j` / `Down` | 下一个值 |
| `Space` | 切换当前值选择状态 |
| `Enter` | 提交草稿 |
| `Esc` | 取消草稿 |

### Monitor 调整器

在 Monitor 图表视图按 `m` 或 `M`。`a` 切换页面；`Enter`、换行或 `Esc` 关闭调整器。控制如下：

| 页面 | 控制 |
| --- | --- |
| Quick | 时间线样式：`w` 窗口与 `i` 采样间隔；`cumulative-bars`：`w` 今天/昨天、`g` 每小时/30 分钟与 `i` 采样间隔；ranking/list 不显示 `w`；所有适用样式保留 `b` 分组、`+/-` Top、`d` 密度、`t/T` 主题和 `s` 样式 |
| Advanced | `f` 筛选；按项目分组时 `A` 项目聚合和 `P` 项目名称上下文；`l` 图例 |

分组和筛选需要新的匹配观测基线；窗口变化会立即重投影保留的观测值。间隔变化时，Monitor 会重建
调度器。仅外观修改不会假装重建此前的观测历史。

### Dashboard 控制

Dashboard 有独立的导航和归属规则。浏览模式中：

| 按键 | 行为 |
| --- | --- |
| `r` | 仅在图表浏览模式刷新全部 Pane；完整命令视图中无操作。 |
| `s` | 调整第一个 Pane。 |
| 鼠标点击 | 调整被点击的 Pane。 |
| `g` | 打开全局 Dashboard 调整。 |
| `h` / `H` | 图表浏览模式中切换 Dashboard 控制栏；完整命令视图中小写 `h` 跳到首行，`H` 无操作。 |
| `e`、`Up` / `Down` | 完整 Dashboard 命令视图中跳到末行或逐渲染行滚动。 |
| `v` | 显示完整 Dashboard 命令。 |
| `y` | 从命令视图复制。 |
| `Space` | 仅在图表浏览模式暂停/恢复 Dashboard 调度；完整命令视图中无操作。 |
| `Ctrl-C` | 退出。 |

调整 Pane 时，`v` 切换其视图。非图表 Pane 文字视图中，`Up`/`Down` 逐行滚动，`h` 跳到首行，`e`
跳到末行；Pane 通知保持固定。始终显示的控制栏只保留阅读、复制和视图切换操作，且仅在文字溢出时提示滚动；`r` 和 `Space` 在此无操作，显示文字时不提供图表 Quick/Advanced 控制和 Dashboard Pane 管理。按 Enter、`Esc` 或发生无操作超时会结束调整，并将所有 Pane 恢复为图表视图。图表视图中，`r` 替换；`N` 在前插入；`n` 在后插入；当 Pane 多于一个时 `x`
删除；`[`/`]` 重排；`Tab` 切到下一个 Pane。`{`/`}` 调整逻辑列份额；`_`/`=` 调整逻辑行份额。
聚焦 Pane 的快捷键使用上面的历史/Monitor 图表控制，包含仅在项目分组时可用的 Advanced `A` 和 `P`；
但 Monitor 没有 `i`，因为采样属于 Dashboard Host。全局 Dashboard 调整中，`t/T` 调整外壳主题，`s` 调整外壳样式，`h` 调整 Header
样式，`u` 调整 Header 汇总，`z` 调整布局。按 `z` 会打开布局选择器：使用 `j`/`k` 或方向键选择
兼容布局，按 `Enter` 应用，按 `Esc` 取消。无法容纳当前 Pane 数量的固定容量布局仍会列出并标为不可用，
导航会跳过这些选项。

<!-- guide:troubleshooting -->

## 约束与排障

| 情况 | 处理方式 |
| --- | --- |
| 实时查询找不到 `ccusage` | 安装 `ccusage`、将其放入 `PATH`，或传入 `--ccusage-bin`。无需它即可用 `--demo` 探索。 |
| 图表过小或被截断 | 放大终端、降低密度，或使用更窄的 Dashboard 预设/布局。渲染器会执行最小可用尺寸约束。 |
| 分组 Timeline 拒绝 `area` | 改用其他 Timeline 样式，或取消分组。 |
| 分组 Monitor 拒绝 `bars` | 改用线形/排名/列表 Monitor 样式，或取消分组。 |
| `--top` 被拒绝 | 使用正值，并在需要处提供分组维度。 |
| `--ascii` 与主题冲突 | 省略显式 `--theme`；Dashboard 中也要省略显式 Pane 主题。 |
| Dashboard 命令被拒绝 | 使用预设，或至少提供一个带引号的 `--pane`；不要将预设和 `--grid` 混用，也不要将 `--layout` 与预设/网格混用。 |
| Pane 片段被拒绝 | 将 Host/生命周期参数放在 Dashboard 层；片段只描述图表。 |
| Monitor 没有显示旧吞吐历史 | 这是预期行为：它只观测当前进程采集到的快照。 |
| 退出后运行时调整消失 | 这是预期行为：调整仅属于会话；如需复用，请自行保存复制出的命令。 |

关于间歇性的 `unified_daily` 本地 Agent 数据库访问失败，请参阅[已知问题](known-issues.zh-CN.md)。

使用 `ccuv --help` 查看路由列表，使用 `ccuv <command> --help` 查看本地化解析器帮助，例如
`ccuv --lang zh dashboard --help`。常规帮助刻意省略高级 `--query-timeout`、Dashboard 权重参数和
Monitor 中“解析器接受但使用无效”的 `--no-watch`；本文记录它们以明确约束。
