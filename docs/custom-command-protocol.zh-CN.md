# 自定义命令协议指南

[English](custom-command-protocol.md)

`ccuv custom` 用一个命令适配可相加的历史指标，可用于阅读、CI 活动、金额、构建次数或字节总量等数据。ccuv 负责终端呈现；命令负责数据源特有的查询与聚合。

这是命令协议，不是插件或持久化系统。v1 不支持文件、HTTP、stdin、Python 插件或 Monitor 数据源；也不支持已完成结果缓存、命令发现、范围合并或不可相加指标。

## 启动自定义图表

选择图表类型，并提供稳定的数据集 ID 与命令 argv：

```bash
ccuv custom timeline --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom stack --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom calendar --dataset wechat-reading --command 'wechat-reading ccuv'
ccuv custom ranking --dataset wechat-reading --command 'wechat-reading ccuv'
```

`--dataset` 必填，是数据源的稳定身份；每个响应都必须原样回显它。`--command` 使用 `shlex.split` 拆成 argv，并且不经 shell 执行。若明确需要 shell 行为，请自行将 shell 放入 argv：

```bash
ccuv custom timeline --dataset example --command "sh -lc 'collector | adapter'"
```

自定义图表初始为 14 天、未分组总计的图表窗口和按天汇总；自定义数据不能用于 `monitor`。Dashboard Pane 始终提供 `p`/`P` 修改滚动图表范围。首次成功响应后，才会按 capability 额外提供查询控制：`g` 循环已声明粒度，`b` 循环总计与已声明分组，`f` 编辑已声明的筛选选项；这些调整都会发起新的命令查询。还提供数据源编辑（`e`）和诊断日志（`L`）。小写 `l` 循环自定义 Timeline/Stack 的图例；大写 `L` 专用于日志。

独立运行的自定义图表会持续向配置的命令发送 `ccuv.custom/v1` Chart 请求以刷新数据，不会执行 `ccusage` 的历史采集或 watch 处理。影响数据的替换请求会立即显示候选图表的标题和加载状态，不显示旧事实或“查询中”标记；请求失败后，ccuv 会恢复此前已接受的图表，并在旁边显示自定义数据源错误。

## 在 Dashboard 中使用自定义 Pane

使用普通的、有序 `--pane` 片段。同一数据集可出现在多个 Pane 中，但每次使用必须有相同的命令配置。

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'empty' \
  --pane 'custom timeline --dataset wechat-reading --command "wechat-reading ccuv"' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

`dashboard --empty` 会关闭默认 ccusage Pane 及其默认数据依赖。它使用普通默认 Dashboard 布局并填入 `empty` Pane；`--grid` 或显式 layout 决定初始空 Pane 的数量和位置。它不会添加时钟。已有 `wide-clock` 和 `narrow-clock` 预设仍保留时钟 Pane。

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

Chart 请求使用包含首尾日期的日历日期。v1 没有时间戳、时区、小时、滚动窗口或日内字段。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "wechat-reading",
  "range": {"start_date": "2026-09-17", "end_date": "2026-09-30"},
  "query": {
    "filters": {"category": ["literature"]},
    "group_by": "book",
    "granularity": "day"
  }
}
```

`range` 提供图表覆盖范围；`query` 提供由数据源处理的业务筛选、分组和聚合。ccuv 不会发送样式、主题、密度、图例、排序、Top N、Other、Pane 几何或布局。

汇总请求携带一个用户可见 scope 的、已解析且包含首尾的区间。ccuv 负责所有日历换算；命令必须直接使用这些区间，不能自行重建“本月”或比较区间。只会发送实际存在的比较区间。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-summary-id",
  "request_kind": "summary",
  "dataset_id": "wechat-reading",
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

Dashboard 每个数据集 ID 显示一项汇总：按 Pane 可见顺序扫描，并在 Header 刷新边界选择该 ID 第一个 Pane 的命令与筛选上下文；相同 ID 的各 Pane 仍独立查询。相同 ID 的命令编辑不会立即替换 Header 已接受的结果，直到之后由 Header 发起刷新。Header 指标不会与 token 总计相加。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-summary-id",
  "request_kind": "summary",
  "dataset_id": "wechat-reading",
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

成功的 Chart 响应包括 `protocol`、`request_id`、`request_kind`、`dataset_id`、`status: "ok"`、`dataset`、`capabilities` 和 `data`。成功的 Summary 响应只包含 `summary.metric`。数据集标题/描述、单位标签、维度/筛选标签和选项、系列标签、指标标签、数据源展示文本和返回消息都必须同时提供 `en` 与 `zh-CN`；ccuv 选择当前应用语言。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "wechat-reading",
  "status": "ok",
  "dataset": {
    "title": {"en": "WeChat Reading", "zh-CN": "微信读书"},
    "description": {"en": "Daily pages read", "zh-CN": "每日阅读页数"},
    "unit": {"id": "page", "label": {"en": "pages", "zh-CN": "页"}, "placement": "suffix", "decimal_places": 0}
  },
  "capabilities": {},
  "data": {"series": [{"id": "book-001", "label": {"en": "One Hundred Years of Solitude", "zh-CN": "百年孤独"}, "points": [{"date": "2026-09-17", "value": "28"}]}]}
}
```

所有指标值与比较基准值都必须是普通带符号十进制表示法的十进制**字符串**。ccuv 将其解析为精确 `Decimal`。JSON 数字、空字符串、科学计数法、`NaN` 和无穷值均无效。每个数据集图表指标只能有一个固定单位和维度，且必须可相加。支持的例子包括计数、金额和字节总量；平均值、比率、百分比、独立用户数、最小/最大值、百分位数、余额和快照不在范围内。

命令需筛选所请求的闭区间，应用业务规则，按请求维度聚合（未分组则返回唯一 `total`），并返回全部候选系列。ccuv 负责候选排序、Top N、Other、累计显示形式、比较与所有呈现。不要预先挑选 Top N、替换不支持的请求，或返回已经格式化的数字/百分比。

## Capabilities 与图表

每次成功响应都返回完整、稳定的 capability manifest。它描述支持的查询面，而不是快捷键映射。v1 只提供枚举的多选筛选；不支持文本/范围/正则筛选、分页、搜索或层级筛选。不支持的分组、筛选、粒度或组合必须被拒绝，不能静默削弱或改写请求。

每个图表声明允许的粒度、分组维度和筛选。Timeline、Stack、Ranking 接收总计或分组日期系列；Calendar 必须是未分组的每日总计。协议与投影会校验范围、分组、粒度、筛选 ID 和已选筛选项 ID。Dashboard 只有在成功响应声明相应 capability 后才显示 `g`、`b`、`f`，绝不会削弱不支持的选择。本地 Top N/Other 调整只影响展示，不会发起命令查询。

汇总值使用当前筛选，但不继承分组、Top N 或 Other。汇总响应恰好返回一个 `metric`：`current.value` 和已就绪比较的 `base_value` 是 Decimal 字符串，`current.display` 是由数据源权威提供的本地化主显示文本。`ready` 必含 `base_value`；`pending` 和 `unavailable` 必须省略它。ccuv 负责比较方向、百分比、颜色与周边本地化文案。周汇总请求上一个完整周且省略同比；年汇总省略环比；显式固定范围省略两种比较。

## 错误、数据源编辑与日志

协议错误是一个有效 JSON 响应，包含 `status: "error"`、本地化消息，以及下列稳定 code 之一：

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "dataset_id": "wechat-reading",
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

发生数据源查询失败后，ccuv 保留最后有效的结果与渲染，并在旁边显示错误；候选数据源配置保留，以便继续修正。空系列不是错误：返回 `status: "ok"`、空系列列表和有效的零值/`pending`/`unavailable` 汇总即可。

格式错误的输出、ID 不匹配、无效十进制、缺失本地化文本、未知协议版本、超时、启动失败，以及没有有效协议错误的非零退出都是 source/protocol failure。stderr 可以作为有界诊断展示，但绝不会作为结果解析。

仅精确等价且同时进行的请求会合并。身份包括 argv 与执行上下文、数据集 ID、请求类型、包含首尾的范围、规范化筛选（键与选项均排序）、分组、粒度和汇总周期/截至日期；不包括图表类型、样式、主题、密度、图例、Top N、Other、布局或 Pane 位置。v1 不支持重叠范围合并、interval/范围并集、已完成结果缓存、批处理或结果切片。

自定义 Dashboard Pane 提供 **Source**（`e`），通过可 Tab 导航的表单编辑 Dataset ID 与 argv。按 Enter 会验证草稿并发起查询。影响数据的替换请求会立即显示候选标题和加载状态，而不是此前图表；查询失败后会恢复已接受的渲染并显示错误。`L` 打开每个 Pane 的有界 **Logs**，`y` 可复制；小写 `l` 循环 Timeline/Stack 图例。Logs 仅包含成功查询诊断和失败信息，绝不会解析或展示协议 stdout 作为结果数据。
