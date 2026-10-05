# 自定义命令协议指南

[English](custom-command-protocol.md)

`ccuv custom` 用一个命令适配可相加的历史指标，可用于阅读、CI 活动、金额、构建次数或字节总量等数据。ccuv 负责终端呈现；命令负责数据源特有的查询与聚合。

这是命令协议，不是插件或持久化系统。v1 不支持文件、HTTP、stdin、Python 插件或 Monitor 数据源；也不支持已完成结果缓存、命令发现、范围合并或不可相加指标。

## 启动自定义图表

选择图表类型和稳定的 Dataset ID，并且只选择一种数据源：

```bash
# 已安装 Dataset：只需图表类型和 Dataset ID。
ccuv chart timeline --dataset weread

# 开发者任意命令：图表类型、Dataset ID 与命令 argv。
ccuv chart timeline --dataset example --command 'example-reader ccuv'
ccuv chart stack --dataset example --command 'example-reader ccuv'
ccuv chart calendar --dataset example --command 'example-reader ccuv'
ccuv chart ranking --dataset example --command 'example-reader ccuv'
```

`--dataset` 必填，是数据源的稳定身份；每个响应都必须原样回显它。不提供 `--command` 时，`--dataset ID` 会解析并验证本地已安装 Dataset，不要求用户提供可执行文件路径。`--command` 使用 `shlex.split` 拆成 argv，并且不经 shell 执行。若明确需要 shell 行为，请自行将 shell 放入 argv：

```bash
ccuv chart timeline --dataset example --command "sh -lc 'collector | adapter'"
```

自定义图表初始为 14 天、未分组总计的图表窗口和按天汇总；自定义数据不能用于 `monitor`。Dashboard Pane 始终提供 `p`/`P` 在共享滚动范围序列 `7d → 14d → 30d → 90d → 180d → 365d → 1w → 1mo → 1y` 中循环；`1w`、`1mo`、`1y` 分别表示本周、本月和本年。首次成功响应后，才会按 capability 额外提供查询控制：`g` 循环已声明粒度，`b` 循环总计与已声明分组，`f` 编辑已声明的筛选选项；这些调整都会发起新的命令查询。`r` 打开替换流程，可重新选择 Dataset 并在本地命令模式下编辑命令；`L` 显示诊断日志。小写 `l` 循环自定义 Timeline/Stack 的图例；大写 `L` 专用于日志。

独立运行的自定义图表会持续向配置的命令发送 `ccuv.custom/v1` Chart 请求以刷新数据，不会执行 `ccusage` 的历史采集或 watch 处理。影响数据的替换请求会立即显示候选图表的标题和加载状态，不显示旧事实或“查询中”标记；同一查询的刷新失败可以保留已接受图表并显示错误，但替换查询失败绝不会显示另一选择的数值事实，只保留候选标题、范围和错误。

## 在 Dashboard 中使用自定义 Pane

使用普通的、有序 `--pane` 片段。同一数据集可出现在多个 Pane 中，但每次使用必须有相同的数据源配置。已安装 Dataset Pane 只需图表类型与 Dataset ID；任意命令仍可用于开发者集成。

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'empty' \
  --pane 'custom timeline --dataset weread' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

Dashboard 预设仍是内置的 token 消耗统计模板；添加 Dataset Pane 不会创建或修改 Dataset 预设。

`dashboard --empty` 会关闭默认 ccusage Pane 及其默认数据依赖。它使用普通默认 Dashboard 布局并填入 `empty` Pane；`--grid` 或显式 layout 决定初始空 Pane 的数量和位置。它不会添加时钟。已有 `wide-clock` 和 `narrow-clock` 预设仍保留时钟 Pane。

选中自定义 Dashboard Pane 后，`v` 和 `V` 可在图表、紧凑命令、完整命令、数据表和 JSON 视图间向前/向后循环。数据视图序列化 ccuv 当前本地投影的图表数据，遵守当前范围、筛选、分组、粒度、Top/Other 选择和单位精度。JSON 会同时保留规范 series ID、Decimal 字符串值和本地化显示名称，不会暴露不透明的原始进程响应。

`--pane 'empty'` 是真实的临时 Pane：它参与布局、焦点、鼠标与 Tab 导航、插入、删除和复制命令序列化，但没有 Provider、调度、数据或汇总。它恰好显示两行：

```text
空白子图
双击选中，然后按 r 选择类型
```

双击空 Pane 会进入其 Dashboard 管理上下文，只显示 Dashboard 结构和位置操作，不显示图表专属设置。`r` 打开共用的替换类型选择器；`N` 和 `n` 分别打开前插和后插选择器。选择 Custom 后，再选择 Timeline、Stack、Calendar 或 Ranking，并填写 Dataset ID 和 Command。替换后新的自定义 Pane 会立即发起初始查询；若失败，Pane 会显示对应数据源错误。插入操作也可以创建 Empty Pane。按 `x` 删除 Pane 会压缩其余 Pane，不会自动留下替代空位。

## 进程契约

每个物理查询执行一个命令进程：

1. ccuv 启动配置好的 argv。
2. ccuv 向 stdin 写入**恰好一个** UTF-8 JSON 请求，然后关闭 stdin。
3. 命令向 stdout 写入**恰好一个** UTF-8 JSON 响应，然后退出。
4. stderr 仅是有界诊断输出，绝不是协议数据。
5. ccuv 验证超时、退出状态、JSON、版本、ID、schema 和十进制数值。

协议标识为 `ccuv.custom/v1`。ccuv 为每次物理执行生成 `request_id`。等价的 Dashboard 进行中请求可能合并，因此该 ID 代表一次共享执行，而不是 Pane 生命周期。

第一次普通 Chart 请求也用于发现 capability，不存在单独的 `describe` 请求。每次成功 Chart 响应都必须自描述，携带完整 capability manifest、本地化数据集元数据和数据；汇总事实通过独立请求返回。命令必须是无状态的：不能依赖此前的命令进程响应。

## 请求

Chart 请求使用包含首尾日期的日历日期，并且必须提供 IANA `timezone`。ccuv 会在每次请求前解析全局 `--timezone`（省略时使用本机系统 IANA 时区）。时区是请求上下文而非 capability：它说明 ccuv 如何解释日期边界。v1 没有时间戳、小时或日内字段。`range.period` 是 `ccuv.custom/v1` 内的附加元数据，用于传递选中的滚动档位；它既不替代绝对日期边界，也不改变协议版本。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "weread",
  "timezone": "Asia/Shanghai",
  "range": {"start_date": "2026-09-17", "end_date": "2026-09-30", "period": "14d"},
  "query": {
    "filters": {"category": ["literature"]},
    "group_by": "book",
    "granularity": "day"
  }
}
```

`range.start_date` 和 `range.end_date` 是已解析、包含首尾且具有最高优先级的图表覆盖范围。`range.period` 是滚动档位的规范写法；`1w`、`1mo`、`1y` 分别传达本周至今、本月至今和本年至今的语义，固定 `--since`/`--until` 范围则为 `null`。数据集可以用它处理数据源特有语义，但不能替换携带的绝对日期。`query` 提供由数据源处理的业务筛选、分组和聚合。ccuv 不会发送样式、主题、密度、图例、排序、Top N、Other、Pane 几何或布局。

汇总请求携带一个用户可见 scope 的、已解析且包含首尾的区间。ccuv 负责所有日历换算；命令必须直接使用这些区间，不能自行重建“本月”或比较区间。只会发送实际存在的比较区间。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-summary-id",
  "request_kind": "summary",
  "dataset_id": "weread",
  "timezone": "Asia/Shanghai",
  "query": {"filters": {"category": ["literature"]}},
  "summary": {
    "scope": "month",
    "intervals": {
      "current": {"start_date": "2026-09-01", "end_date": "2026-09-30"},
      "sequential": {"start_date": "2026-08-01", "end_date": "2026-08-30"},
      "year_over_year": {"start_date": "2025-09-01", "end_date": "2025-09-30"}
    }
  }
}
```

Dashboard 每个数据集 ID 显示一项汇总：按 Pane 可见顺序扫描，并使用该 ID 第一个 Pane 的命令；相同 ID 的各 Pane 仍独立查询。Header 汇总始终使用空筛选，并忽略 Pane 的分组、粒度、图表范围和展示设置。当该 Pane 的命令发生变化时，ccuv 会立即隐藏此前已接受的 Header 指标，并发起新的 Header 所有的刷新。Header 指标不会与 token 总计相加。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-summary-id",
  "request_kind": "summary",
  "dataset_id": "weread",
  "status": "ok",
  "summary": {
    "metric": {
      "id": "pages-read",
      "label": {"en": "Pages read", "zh-CN": "阅读页数"},
      "current": {
        "value": "68",
        "display": {"en": "68 pages", "zh-CN": "68 页"}
      },
      "sequential": {"status": "ready", "base_value": "56"},
      "year_over_year": {"status": "ready", "base_value": "50"}
    }
  }
}
```

## 成功响应与数值

成功的 Chart 响应包括 `protocol`、`request_id`、`request_kind`、`dataset_id`、`status: "ok"`、`dataset`、`capabilities` 和 `data`。成功的 Summary 响应包含 `summary.metric`。两类成功响应都可额外包含非阻断的 `warnings` 数组；每个 warning 具有开放集合的稳定 `code` 和本地化 `message`，ccuv 会显示它，同时保留成功的图表或汇总。数据集标题/描述、单位标签、维度/筛选标签和选项、系列标签、指标标签、数据源展示文本和返回消息都必须同时提供 `en` 与 `zh-CN`；ccuv 选择当前应用语言。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "weread",
  "status": "ok",
  "warnings": [
    {
      "code": "timezone_not_supported",
      "message": {
        "en": "WeRead uses Asia/Shanghai; the requested timezone was not applied.",
        "zh-CN": "微信读书使用 Asia/Shanghai；未应用请求的时区。"
      }
    }
  ],
  "dataset": {
    "title": {"en": "WeRead", "zh-CN": "微信读书"},
    "description": {"en": "Daily pages read", "zh-CN": "每日阅读页数"},
    "unit": {"id": "page", "label": {"en": "pages", "zh-CN": "页"}, "placement": "suffix", "decimal_places": 0}
  },
  "capabilities": {},
  "data": {"series": [{"id": "book-001", "label": {"en": "One Hundred Years of Solitude", "zh-CN": "百年孤独"}, "points": [{"date": "2026-09-17", "value": "28"}]}]}
}
```

所有指标值与比较基准值都必须是普通带符号十进制表示法的十进制**字符串**。ccuv 将其解析为精确 `Decimal`。JSON 数字、空字符串、科学计数法、`NaN` 和无穷值均无效。每个数据集图表指标只能有一个固定单位和维度，且必须可相加。支持的例子包括计数、金额和字节总量；平均值、比率、百分比、独立用户数、最小/最大值、百分位数、余额和快照不在范围内。

例如，WeRead Dataset 当前以 `Asia/Shanghai` 作为数据源日期口径。它会接受每个有效的请求时区；当请求时区不是 `Asia/Shanghai` 时，仍按上海口径成功返回数据，并附加 `timezone_not_supported` warning，而不是将成功查询变为错误。Dataset 应准确声明自己的单位与精度；WeRead 的阅读时长单位为分钟，日值和汇总值保留两位小数，汇总先聚合原始秒数再转换并舍入，因此已舍入日值的简单相加可能与汇总相差 `0.01` 分钟。

命令需筛选所请求的闭区间，应用业务规则，按请求维度聚合（未分组则返回唯一 `total`），并返回全部候选系列。ccuv 负责候选排序、Top N、Other、累计显示形式、比较与所有呈现。不要预先挑选 Top N、替换不支持的请求，或返回已经格式化的数字/百分比。

## Capabilities 与图表

每次成功响应都返回完整、稳定的 capability manifest。它描述支持的查询面，而不是快捷键映射。v1 只提供枚举的多选筛选；不支持文本/范围/正则筛选、分页、搜索或层级筛选。不支持的分组、筛选、粒度或组合必须被拒绝，不能静默削弱或改写请求。

每个图表声明允许的粒度、分组维度和筛选。Timeline、Stack、Ranking 接收总计或分组日期系列；Calendar 必须是未分组的每日总计。数据源特有的能力组合规则由 Dataset 自己负责——例如已声明的分组仅在特定 `range.period` 下可用时，Dataset 应返回关联到原请求的 `unsupported_query`。ccuv 原样发送用户选中的查询：不维护 Dataset 专属兼容矩阵、不替换为总计，也不改选其他时间档位。协议与投影会校验周期语法、分组、粒度、筛选 ID 和已选筛选项 ID。Dashboard 只有在成功响应声明相应 capability 后才显示 `g`、`b`、`f`。本地 Top N/Other 调整只影响展示，不会发起命令查询。

Dataset 可以在 Ranking 响应中为官方周期汇总的每个实体提供一个位于请求 `end_date` 的点。该点是 Ranking 投影的坐标，不代表按日归因；其值是数据源已聚合的结果。除非也拥有相应的真实数据，Dataset 只能为 Ranking 声明这类分组，不应为 Timeline、Stack 或 Calendar 声明。

汇总值使用当前筛选，但不继承分组、Top N 或 Other。汇总响应恰好返回一个 `metric`：`current.value` 和已就绪比较的 `base_value` 是 Decimal 字符串，`current.display` 是由数据源权威提供的本地化主显示文本。`ready` 必含 `base_value`；`pending` 和 `unavailable` 必须省略它。ccuv 负责比较方向、百分比、颜色与周边本地化文案。周汇总请求上一个完整周且省略同比；年汇总省略环比；显式固定范围省略两种比较。

## 错误、数据源编辑与日志

协议错误是一个有效 JSON 响应，包含 `status: "error"`、本地化消息，以及下列稳定 code 之一：

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "weread",
  "status": "error",
  "error": {
    "code": "unsupported_query",
    "message": {"en": "Monthly grouping by author is not available.", "zh-CN": "暂不支持按作者进行月度聚合。"},
    "unsupported": {"field": "query.granularity", "value": "month"}
  }
}
```

- `unsupported_dataset`
- `unsupported_chart_kind`
- `unsupported_query`
- `invalid_request`
- `invalid_filter`
- `range_not_available`
- `source_unavailable`
- `internal_error`

`unsupported` 可选，但 Dataset 应为每个可由用户修正的选择失败提供它。其精确 `field` 和请求的 `value` 标识被拒绝的控制项。特别是当选中的滚动周期不可用时，应使用 `{"field": "range.period", "value": "<period>"}`。ccuv 此时会清除旧图表：继续保留会让用户误以为周期切换未生效。对于其他字段，若已有已接受图表，ccuv 会保留它并在旁边显示警告。其他替换请求失败时，若请求身份不同则会清除旧数值事实，并展示带候选选择标题的错误状态。

Dataset 错误消息应为本地化、面向用户的可操作文案。两种语言都应指出被拒绝的选择，并在适用时列出受支持的替代项。不得规定 ccuv 的快捷键或控件：Dataset 可运行于多个宿主，当前界面可用控件由宿主呈现。不要静默替换为其他周期或查询。

ccuv 会比较失败请求与已接受查询的数据影响身份：数据源、图表类型、包含首尾的范围及 `range.period`、筛选、分组和粒度。同一查询的刷新失败可以保留有效事实；替换查询失败会清除数值事实，只保留本地化 Dataset 元数据以显示候选标题和范围。这一规则与 Dataset 无关，不依赖特定周期、Dataset ID 或数据源端点。空系列不是错误：返回 `status: "ok"`、空系列列表和有效的零值/`pending`/`unavailable` 汇总即可。

格式错误的输出、ID 不匹配、无效十进制、缺失本地化文本、未知协议版本、超时、启动失败，以及没有有效协议错误的非零退出都是 source/protocol failure。stderr 可以作为有界诊断展示，但绝不会作为结果解析。

仅精确等价且同时进行的请求会合并。身份包括 argv 与执行上下文、数据集 ID、请求类型、时区、包含首尾的范围**及其 `range.period` 语义**、规范化筛选（键与选项均排序）、分组、粒度和汇总周期/截至日期。因此，即使解析后的日期相同，只要选中的周期语义不同，也绝不会合并执行。不包括图表类型、样式、主题、密度、图例、Top N、Other、布局或 Pane 位置。v1 不支持重叠范围合并、interval/范围并集、已完成结果缓存、批处理或结果切片。

自定义 Dashboard Pane 提供 **Source**（`e`）。已安装 Dataset Pane 只编辑图表类型与 Dataset ID，然后重新验证本地安装；任意命令 Pane 通过可 Tab 导航的表单编辑 Dataset ID 与 argv。按 Enter 会验证草稿并发起查询。影响数据的替换请求会立即显示候选标题和加载状态，而不是此前图表；同一查询的刷新失败可以保留已接受事实并显示错误，替换查询失败时只保留候选标题、范围和错误。`L` 打开每个 Pane 的有界 **Logs**，`y` 可复制；小写 `l` 循环 Timeline/Stack 图例。Logs 仅包含成功查询诊断和失败信息，绝不会解析或展示协议 stdout 作为结果数据。
