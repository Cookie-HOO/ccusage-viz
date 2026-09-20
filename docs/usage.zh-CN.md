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
| `--period PERIOD` | 正整数加 `d`、`mo`、`q` 或 `y`，如 `14d`、`13mo`、`1q` | Timeline/Stack/Ranking：`14d`；Calendar：`365d` | 历史路由 | 以所选时区的今天结束的滚动范围。 |
| `--since YYYY-MM-DD` | ISO 日期 | 未设置 | 历史路由 | 固定或开放范围的起始日期。 |
| `--until YYYY-MM-DD` | ISO 日期 | 未设置 | 历史路由 | 固定范围的结束日期；需要 `--since`。 |
| `--timezone IANA_ZONE` | 有效 IANA 时区，如 `Asia/Shanghai` | 本地时区 | 历史路由 | 解析“今天”和相对边界。 |
| `--agent VALUE` | 可重复文本 | 无 | 历史路由与 Monitor | 按 Agent 筛选。 |
| `--model VALUE` | 可重复文本 | 无 | 历史路由与 Monitor | 按模型筛选。 |
| `--project VALUE` | 可重复文本 | 无 | 历史路由与 Monitor | 按项目筛选。 |
| `--interval SECONDS` | 有限数字；历史图表至少 `2` | `10` | 历史路由 | 监听时的刷新节奏。 |
| `--no-watch` | 标志 | 关闭 | 历史路由 | 仅查询一次后退出，不持续监听。 |

同一维度重复筛选值表示匹配其中任一个值，不同维度之间同时生效。例如，以下表示
**Agent A 或 B**，使用**模型 X**，且属于**项目 one 或 two**：

```bash
ccuv timeline --agent A --agent B --model X --project one --project two
```

匹配不区分大小写。精确匹配优先；唯一的包含匹配可接受；有歧义的包含匹配必须进一步缩小。
项目身份以 Agent 为作用域，因此显示名相同的项目仍可能是不同项目。

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
| 无效时区 | `--timezone` 必须是已安装的 IANA 时区名称。 |
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
| `--style` | `bar`（默认）、`dot`、`dots` | 排名呈现方式。 |

### Monitor

```bash
ccuv monitor --window 30m --by model --top 5 --style ranking
```

Monitor 在本次运行期间从重复累计快照观测吞吐量。第一个被接受的快照建立基线；观测历史仅属于
当前进程，进程退出后即消失。

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
| `--timezone IANA_ZONE` | 未给出时为本地时区 | Host Pane 的历史时间解释。 |
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
--interval --no-watch --watch --timezone --ascii --demo --lang
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
| `r` | 刷新历史查询，或立即请求一个 Monitor 样本。 |
| `h` | 显示/隐藏仅当前会话的控制栏。 |
| `v` | 依次切换图表、紧凑命令、完整命令、Markdown 表格、JSON，再回到图表。 |
| `y` | 从非图表文本视图复制当前命令/数据。 |
| `Space` | 暂停/恢复调度。 |
| `m` | 仅在图表视图打开调整。 |
| `s` / `d` / `l` | 在支持的调整器中分别控制样式/密度/图例。 |

紧凑命令视图省略默认值和私有项目路径。完整命令视图包含实际生效的设置，包括私有项目路径、
选定的二进制路径和 query timeout。复制不等于持久化：程序不会自动写入配置。运行时调整仅在当前
进程存活；若要复用，请自行保存复制出的命令。

### 历史图表调整流程

Timeline、Calendar、Stack 和 Ranking 在图表视图按 `m` 打开调整器。调整器会预览修改；`a` 在
**Quick** 和 **Advanced** 页之间切换；`Enter`/换行提交当前候选配置；`Esc` 取消调整器。
仅视觉修改会立即更新预览；影响数据的修改会在提交后的配置刷新中使用。

| 图表 | Quick 页 | Advanced 页 |
| --- | --- | --- |
| Timeline | `p/P` 范围；`g` 粒度；`b` 分组；`+/-` Top；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选；`o` Other；`l` 图例；`k` 星期标签 |
| Calendar | `p/P` 范围；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选 |
| Stack | `p/P` 范围；`g` 粒度；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选；`c` 缓存模式；`l` 图例；`k` 星期标签 |
| Ranking | `p/P` 范围；`b` 分组；`+/-` Top；`d` 密度；`t/T` 主题；`s` 样式 | `f` 筛选；`o` Other |

`p` 循环尾随预设（`7d`、`14d`、`30d`、`365d`）；`P` 循环自然周期预设（`1mo`、`1q`、`1y`）。
二者都不会修改固定的显式日期范围。分组/样式变化会维持兼容样式；例如 Timeline 改为分组时，
`area` 会替换为兼容样式。

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
| Quick | `w` 窗口；`i` 采样间隔；`b` 分组；`+/-` Top；`d` 密度；`t/T` 主题；`s` 样式 |
| Advanced | `f` 筛选；`l` 图例 |

窗口、间隔、分组和筛选的修改影响观测/采样配置。间隔变化时，Monitor 会重建调度器。仅外观修改不会
假装重建此前的观测历史。

### Dashboard 控制

Dashboard 有独立的导航和归属规则。浏览模式中：

| 按键 | 行为 |
| --- | --- |
| `r` | 刷新全部 Pane。 |
| `s` | 调整第一个 Pane。 |
| 鼠标点击 | 调整被点击的 Pane。 |
| `g` | 打开全局 Dashboard 调整。 |
| `h` | 切换 Dashboard 控制栏。 |
| `v` | 显示完整 Dashboard 命令。 |
| `y` | 从命令视图复制。 |
| `Space` | 暂停/恢复 Dashboard 调度。 |
| `Ctrl-C` | 退出。 |

调整 Pane 时，`v` 切换其视图；`r` 替换；`N` 在前插入；`n` 在后插入；当 Pane 多于一个时 `x`
删除；`[`/`]` 重排；`Tab` 切到下一个 Pane。`{`/`}` 调整逻辑列份额；`_`/`=` 调整逻辑行份额。
聚焦 Pane 的 Quick 键使用上面的历史/Monitor 图表控制，但 Monitor 没有 `i`，因为采样属于
Dashboard Host。全局 Dashboard 调整中，`t/T` 调整外壳主题，`s` 调整外壳样式，`h` 调整 Header
样式，`u` 调整 Header 汇总，`z` 调整布局。

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

使用 `ccuv --help` 查看路由列表，使用 `ccuv <command> --help` 查看本地化解析器帮助，例如
`ccuv --lang zh dashboard --help`。常规帮助刻意省略高级 `--query-timeout`、Dashboard 权重参数和
Monitor 中“解析器接受但使用无效”的 `--no-watch`；本文记录它们以明确约束。
