# 自定义命令协议指南

[English](custom-command-protocol.md)

`ccuv chart <kind> --dataset ID` 将一个可执行 Dataset 命令接入 ccuv。当前 V2 协议支持多个可相加或由数据源拥有的 Metric、历史图表，以及数据源拥有的 Monitor observation；遗留 V1 协议支持一个可相加的历史指标。ccuv 负责终端呈现，命令负责数据源特有的查询与聚合。

这是命令协议，不是插件或持久化系统。ccuv 启动可执行程序，向 stdin 写入一份 JSON 请求，并从 stdout 读取一份 JSON 响应；它不会加载 Python 插件、缓存已完成的命令结果或合并查询范围。V1 不支持 Monitor 或不可相加指标；V2 支持。

## V2 指标

`ccuv.custom/v2` 将边界从“一个 Dataset 一个指标”升级为“一个 Dataset 声明多个指标”。使用顺序是 Dataset、指标、图表类型。命令可声明 `default_metric_id`；用户省略 `--metric` 时优先使用它。没有默认指标时，只有 Dataset 恰好只有一个指标才可省略。

每个指标声明 `aggregation: "sum"` 或 `aggregation: "value"`。`sum` 允许 ccuv 对 Timeline、Stack、Calendar 返回的日期事实做历史投影聚合；`value` 是数据源拥有的最终事实，切换影响数据的范围、分组、筛选或图表选择时 ccuv 必须重新请求，不能跨时间相加或平均。无论采用哪种 aggregation，V2 Ranking 都由 Dataset 为每个条目计算覆盖完整请求范围的标量 `value`；ccuv 仍可在返回条目之间执行排序、Top、Other、占比与比较。非 Ranking 历史图切换粒度时也会重新请求；V2 Ranking 没有粒度。

每个指标既有的必填双语 `description` 是该指标的本地化说明元数据。宿主可在指标选择时将其显示在指标标题下方，并在当前 Pane 帮助中显示。它不改变请求形状、指标 ID、聚合或数据语义。

本地 Dataset 注册会缓存成功的 Probe，用于资源发现、环境状态和非阻塞选择器。再次执行 `ccuv dataset add-local COMMAND` 时，若 Dataset ID 相同，会直接覆盖本地注册并刷新该缓存。Custom Monitor Pane 启动前仍会重新发起 runtime Probe；缓存元数据不作为最终能力权威。

每次成功的 V2 `chart` 和 `monitor` 响应都是完整的 accepted snapshot：同时携带完整 Probe 形状的 `descriptor`、`runtime` 对象与本次 `data` 或 `observation`。首次 Probe 完成 Dataset/Metric 选择后，ccuv 从最近接受响应的 descriptor 读取静态控制能力。`runtime.filters` 为必填项（可以为空），并且是 ccuv 通过 `f` 展示的唯一 filter 目录；Probe descriptor 与静态 chart capability 不再声明 filter 或 option 值。每个 runtime filter 的 `mode` 是 `"multi_select"` 或 `"single_select"`；省略时默认为 `"multi_select"`。两种模式继续使用现有的 option ID 数组查询格式，但 ccuv 对 `single_select` 最多发送一个 ID。空选择是否合法、是否必填仍由 Dataset 权威决定。

Dataset 作者应优先把互斥的源端模式和清晰的范围写成 `single_select`，例如“7 天以内”“30 天以内”“不限”；同时选择多个此类范围既有歧义又不便展示。只有用户确实需要组合互相独立的离散值时才使用 `multi_select`，例如语言、分类、标签、作者或书架标签。

### V2 Metric Group

V2 descriptor 可以在顶层声明有序的 `metric_groups` 数组。每个 Group 有稳定的 Dataset 内 `id` 和必填的双语 `title`。Metric 可通过可选 `group_id` 引用一个已声明 Group：

```json
{
  "metric_groups": [
    {"id": "github-tools", "title": {"en": "GitHub tools", "zh-CN": "GitHub 工具"}}
  ],
  "metrics": [
    {"id": "stars", "group_id": "github-tools", "...": "..."},
    {"id": "updated_days_ago", "group_id": "github-tools", "...": "..."}
  ]
}
```

Group ID 必须唯一，每个 `group_id` 必须引用已声明 Group。允许空 Group。完全省略 `metric_groups` 的 Dataset 与此前 V2 完全兼容：Metric 选择器保持平铺，且没有关联 Metric 快速切换关系。声明 Group 后，宿主按 Group 声明顺序渲染非空 Group，并按 Metric 声明顺序渲染其成员；未提供 `group_id` 的 Metric 保持为所有 Group 后的普通平铺条目。

Group 定义连贯的快速切换边界，不表示共享 Metric 语义。每个 Metric 仍独立拥有单位、aggregation、capability、defaults、summary、数据、display 和源端校验。宿主可以用 `m/M` 在支持当前图表类型的同 Group Metric 间循环；它只发送带目标 `metric_id` 的普通请求，不新增请求字段。

V2 指标可声明 `summary: "comparisons" | "total" | "none"`。`comparisons` 是默认值，允许普通的当前值、环比和同比摘要；`total` 只允许显示一个总数；`none` 不发起 Dataset 摘要请求。每种历史图 capability 都可声明支持的有序 `periods`；声明后 ccuv 会将 `p/P` 限制为该列表。V2 Ranking 可声明正整数 `Ns`、`Nm`、`Nh` 周期，分别表示秒、分钟、小时。Dataset 拥有字符串的原始写法和声明顺序：ccuv 不排序也不规范化，因此 `90s` 始终保持 `90s`。省略 `periods` 时沿用 ccuv 既有 fallback，不会新增内置亚日档位。现有 `d`、`w`、`mo`、`q`、`y`、`all` 语义不变；特别是 `1d` 仍是日历日期周期，不是最近 24 小时。`all` 仅用于 Ranking：ccuv 发送 `period: "all"`，并使用 `1971-01-01` 到今天的锚定范围。权威语义是 marker，不是锚定日期；Dataset 必须按照自身全量数据口径处理。若不支持某个周期，继续使用现有 `unsupported_query`，字段为 `range.period`。

Ranking capability 还可声明 `comparison: "full" | "rank" | "none"`，默认是 `full`。`rank` 仍请求前一等长周期并显示排名变化，但隐藏绝对增长列；`none` 不请求前期，也不显示任何 Ranking 对比列。

Ranking capability 还可声明 `sort_direction: "ascending" | "descending"`；省略时默认 `"descending"`。它是 Dataset 拥有的 Metric 语义，不是宿主偏好：ccuv 会在 Ranking 排序、Top N、Other 和排名对比推导前应用它。它不改变数值事实、单位、Dataset 的 `display` 或对比事实。CLI、Dashboard 和键盘均不提供覆盖项；Metric 切换后直接采用目标 Metric 声明的方向。像“距上次更新天数”这样数值越小越应排前的事实使用 `"ascending"`；Star、增长、评分或数量这类数值越大越应排前的事实使用 `"descending"`。

#### 分区请求兼容性

未声明分区 capability 时，`query.partition_by` 保持省略。Ranking capability 一旦声明 `partition_by`，每个请求都会显式包含当前选择：维度 ID 或 JSON `null`。显式 null 表明支持分区的客户端主动选择了平铺模式。

```json
{
  "chart_kind": "ranking",
  "query": {
    "filters": {},
    "partition_by": "logical_model",
    "group_by": "real_model",
    "top": 3
  }
}
```

每个 V2 历史请求都必须显式携带顶层 `chart_kind`，非 Ranking 请求也一样。V2 Ranking 请求省略 `query.granularity`。遗留 Ranking capability 或 default 即使仍有粒度元数据，ccuv 也只会接受并忽略，不将其用于校验、匹配、刷新或请求身份。

`query.top` 保持数据源覆盖语义。Dataset 自行决定每个 Group 返回多少原始 series，可以少于、等于或多于 N；ccuv 不会将数据源省略的条目推断为零，也不会推断省略的余量。

#### 平铺与分区响应形状

平铺请求（包括已声明且显式为 null 的分区）必须使用既有 `data.series` 容器；非空分区必须使用 `data.groups`。`series` 与 `groups` 互斥。两种容器中的 V2 Ranking 条目都是标量：

```json
{
  "data": {
    "series": [
      {
        "id": "seed-code",
        "label": {"en": "Seed Code", "zh-CN": "豆包代码模型"},
        "value": "7100"
      }
    ]
  }
}
```

分区响应嵌套相同的标量条目：

```json
{
  "data": {
    "groups": [
    {
      "id": "coding",
      "label": {"en": "Coding Model", "zh-CN": "代码模型"},
      "description": {
        "en": "Routes coding workloads",
        "zh-CN": "面向代码场景的逻辑路由"
      },
      "display": {"en": "12.4K requests", "zh-CN": "1.24 万次请求"},
      "comparison_display": {
        "en": "+1.8K requests",
        "zh-CN": "+1800 次请求"
      },
      "link": "https://example.com/router/coding",
      "series": [
        {
          "id": "seed-code",
          "label": {"en": "Seed Code", "zh-CN": "豆包代码模型"},
          "value": "7100"
        }
      ]
    }
  ]
  }
}
```

Group ID 必须唯一。series ID 在同一 Group 内必须唯一，但可在不同 Group 重复；内部条目的稳定身份是 `(group.id, series.id)`。Group 保留 Dataset 响应顺序，并且可以为空。`label` 必填。可选 `description`、`display`、`comparison_display` 和绝对 HTTPS `link` 与 Ranking series 元数据使用相同的本地化、安全和呈现规则。内部 series 使用 V2 Ranking 标量条目 schema 和既有元数据。每个条目必须且只能提供一个十进制字符串 `value`，不得提供 `points`、日期或时间戳。Dataset 负责计算请求范围的权威值——无论是求和、百分位数、增长值还是其他既有源端算法；ccuv 绝不从时序 point 重建。`max_items` 限制所有 Group 返回的内部 series 总数，而不是 Group 数量。任一 Group 或 series 无效都会拒绝整个响应。

ccuv 汇总返回的标量条目形成 Group 总计，再汇总 Group 得到全局总计。协议没有独立的 Group 数值总计字段：可选 `group.display` 只替换格式化文本。对于 `period: "all"`，锚定日期与 `all` marker 保持既有含义，ccuv 不发起上一周期请求。

外层 Group 绝不排序、排名或应用 Top。每个 Group 内，ccuv 独立应用 Metric 的排序方向；值相同时以 series ID 稳定打破平局；序号从 1 重新开始，然后独立应用 Top N。`Other` 是 N 之后实际返回 series 的算术和，由既有设置控制显示或隐藏；绝不从独立总计反推。带符号 Decimal（包括负条目和负 Other）不会被截断或重新解释。

当 `show_percentage: true` 时，Group 占比是该 Group 返回总计除以全局返回总计，条目占比是条目总计除以所在 Group 返回总计。分母在 Top/Other 可见性、搜索和滚动之前确定。全局总计为零时省略 Group 占比；Group 总计为零时省略该 Group 的条目占比。数据源事实可能合理地产生负占比或超过 100% 的占比。

搜索只匹配内部 series 的标签、说明、安全链接可见文字和 URL；不匹配 Group 元数据。没有内部命中行的 Group 会被隐藏。搜索只改变可见性：原始 Group 内排名、总计、占比、柱形比例和比较仍来自最新完整响应。刷新会先重建这些事实，再重新应用未变的搜索文本。Copy All 保持 Dataset Group 顺序并包含 Group 标题，遵守 Top/Other；搜索期间只复制命中的内部 series 及其 Group 标题。

普通比较周期中，平铺条目按 item ID 匹配；分区结果先按 Group ID 匹配，再按稳定 `(group.id, series.id)` pair 匹配。当前和上一周期总计都只使用各自响应实际返回的标量条目；覆盖范围不同的部分不会补零。上一响应不存在的当前 Group 或 series 为新增；series 移到新 Group 后也视为新增。Group 总计可显示数值比较，但没有外层排名变化；内部行保留独立的 Group 内比较。`Other` 不显示比较。

每个图表的 `group_by` 同样是允许发送的有序查询值集合；使用 JSON `null` 明确表示允许未分组总计，维度 ID 仍是字符串，因此名为 `total` 的维度并不冲突。任一已声明列表阻止切换时，ccuv 会保持当前查询并短暂提示，不会发送不支持的请求。不声明 `periods` 时，ccuv 保持原有周期循环，并由 Dataset 动态解释每个请求。

### V2 分区 Ranking

V2 Metric 可以为 Ranking 增加可选外层分区。Metric 可以声明独立的有序分区维度目录；若省略该目录，分区 ID 和标签回退到既有 `capabilities.group_by` 目录。`group_by` ID 始终引用分组目录。

```json
"capabilities": {
  "group_by": [
    {"id": "real_model", "label": {"en": "Real Model", "zh-CN": "真实模型"}}
  ],
  "partition_by": [
    {"id": "logical_model", "label": {"en": "Logical Model", "zh-CN": "逻辑模型"}}
  ],
  "charts": {
    "ranking": {
      "partition_by": [null, "logical_model"],
      "group_by": ["real_model"],
      "show_percentage": true,
      "max_items": 100
    }
  }
}
```

`capabilities.charts.ranking.partition_by` 仅用于 Ranking。省略它会保留旧的平铺 capability 和 wire 格式。声明列表包含 `null` 时允许切回平铺 Ranking；不含 `null` 时分区必填。启用分区后 `group_by` 必须非空，且当前 `partition_by` 与 `group_by` ID 必须不同。每个非空分区 ID 都必须存在于显式分区目录；省略分区目录时则必须存在于分组目录。无效引用或组合会拒绝整个 descriptor，不会静默降级。

### V2 图表默认值

每个指标可通过 `defaults` 建议图表首屏状态。这是尽力而为的查询和呈现建议，不是有效性要求：某个字段无效时 ccuv 会忽略它，继续使用独立图表或 Dashboard 默认值；显式 CLI 或 Dashboard Pane 参数会覆盖同名 Dataset 字段。

```json
"defaults": {
  "timeline": {
    "period": "30d",
    "granularity": "week",
    "group_by": "book",
    "top": 8,
    "other": "hide",
    "style": "line-points",
    "theme": "nord"
  },
  "ranking": {
    "period": "14d",
    "partition_by": "logical_model",
    "group_by": "real_model",
    "top": 3
  },
  "monitor": {"style": "ranking", "window": "6h"}
}
```

所有字段都可省略。`period`、`group_by` 必须受当前图 capability 支持；非 Ranking 的 `granularity` 也必须受支持。遗留的 Ranking `granularity` 默认值可以携带，但会被接受并忽略。`top` 需要最终有效的分组；style 必须与最终分组兼容。`partition_by` 仅可用于 Ranking，并且必须符合已声明分区 capability。非空分区默认值要求 `group_by` 非空且不同；无效默认值组合会拒绝 descriptor。`other` 只能是 `"show"` 或 `"hide"`；`theme` 和 `style` 使用 ccuv 正常 CLI 值。filter 没有静态 default；其 ID 与 option 由响应的 `runtime.filters` 提供。

显式 CLI 与 Dashboard Pane 设置优先于 Dataset 默认值。Dashboard preset 会持久化 `partition_by`；旧 preset 省略它并保持平铺。切换 Metric 需要规范化时，ccuv 先选择目标 Metric 的有效分区默认值；否则在允许时选择 `null`，或选择第一个必填分区，然后再选择不冲突的分组。

`defaults.top` 只表示首屏 Top N 建议。历史 Ranking 可在 `capabilities.charts.ranking.max_items` 声明一个正整数，表示数据源最多能可信返回多少原始排行项目；它不是显示默认值。ccuv 会将当前 Top 写入可选 `query.top`，它同时表示用户希望显示的 Top N 和请求的原始排行覆盖量；在需要诚实计算 `Other` 时，Dataset 可以返回更多项目。请求值为 `null` 表示不限制 Top。用户将 Top 调到超过 `max_items` 时，ccuv 会保留选择并提示数据源上限，而不会发送不可能增加项目的请求。

为兼容旧版 Dataset descriptor，Ranking capability 仍可声明 `descriptions_default: "expanded" | "collapsed"`；ccuv 会接受但忽略该字段。条目说明完全由 Ranking 密度决定：`full` 和 `detailed` 显示，`minimal`、`compact` 和 `normal` 隐藏。

对于 Custom Monitor，`window` 是 ccuv 本地显示范围（`5m` 到 `24h`），不是数据源业务窗口。固定请求窗口始终是 `capabilities.charts.monitor.window_seconds`。

V2 指标可以声明 `monitor`。它声明固定业务口径 `window_seconds`，也可声明 `refresh_interval_seconds`。ccuv 的 Monitor 显示历史仅决定本地可见观测，不会修改指标业务窗口。Dashboard 现有全局采样周期仍是实际周期；若与声明周期不同，会显示警告。Custom Monitor 支持 bars、ranking 和 list，不提供 `cumulative-bars`，因为固定滚动观测不是互不重叠的累计增量。

Custom Monitor 请求包含带时区的 `range.end_at`。Dataset 按声明的固定窗口计算该截止点的总值和分组；无法回答时返回 `range_not_available`，ccuv 显示错误，绝不替换成零。

每个 observation group 可提供可选的本地化 `description` 和 `display` 字段，语义与 Custom Ranking series 的同名元数据一致。Monitor `ranking` 仅在 `full` 或 `detailed` 密度下将 `description` 显示在对应行下方；Monitor `list` 绝不显示说明。`display` 替换 `ranking` 和 `list` 行中的数值文本。数值 `value` 仍是排序、柱长、Top/Other 投影和时序图计算的权威数据；bars 与 timeline 都不使用这两个字段。空本地化字段视为未提供，已提供但格式错误的字段会使响应校验失败。

```json
{
  "protocol": "ccuv.custom/v2",
  "request_id": "pane:router:2",
  "request_kind": "monitor",
  "dataset_id": "router",
  "metric_id": "tokens",
  "timezone": "Asia/Shanghai",
  "range": {"end_at": "2026-10-08T10:00:00+08:00"},
  "query": {"filters": {}, "group_by": "real_model"}
}
```

## 启动自定义图表

选择图表类型和一种数据源。Dataset 会通过只含元数据的 probe 声明稳定 ID；本地命令用户无需自行发明 ID：

```bash
# 已注册 Dataset：只需图表类型和 Dataset ID。
ccuv chart timeline --dataset weread

# 开发者任意命令：图表类型、临时 Dataset ID 与命令 argv。
ccuv chart timeline --dataset example --command 'example-reader ccuv'
ccuv chart stack --dataset example --command 'example-reader ccuv'
ccuv chart calendar --dataset example --command 'example-reader ccuv'
ccuv chart ranking --dataset example --command 'example-reader ccuv'

# 已声明的 V2 分区：在每个逻辑模型中独立排列真实模型。
ccuv chart ranking --dataset router --partition-by logical_model --group-by real_model
```

`--dataset` 必填，是数据源的稳定身份；每个响应都必须原样回显它。不提供 `--command` 时，`--dataset ID` 会解析并验证本地已安装 Dataset，不要求用户提供可执行文件路径。`--command` 使用 `shlex.split` 拆成 argv，并且不经 shell 执行。若明确需要 shell 行为，请自行将 shell 放入 argv：

```bash
ccuv chart timeline --dataset example --command "sh -lc 'collector | adapter'"
```

遗留 V1 图表默认以 14 天、未分组总量图和日周期摘要启动。V2 Metric 可以声明兼容的启动默认值，也可以支持 `monitor`。历史 Dataset Pane 使用 `p`/`P` 循环 Metric 声明的周期；未声明时使用共享 fallback 范围 `7d → 14d → 30d → 90d → 180d → 365d → 1w → 1mo → 1y`；`1w`、`1mo`、`1y` 分别表示本周、本月和本年。首次成功响应后，才会按 capability 额外提供查询控制。普通历史图表中，`g` 循环粒度，`b` 循环总计与已声明分组。支持分区的 Ranking 中，Quick 页 `g/G` 循环已声明外层分区，`b/B` 循环内部排名维度；两个方向都会跳过与另一个当前维度相同的选择，没有替代项时保留有效查询并短暂提示。Quick 页 `s/S` 调整 style；Advanced 页 `s/S` 调整 Ranking spacing，`o` 调整 Other，`f` 编辑筛选。所有 Dashboard 图表 Pane 的筛选都位于 Advanced；聚焦 Dataset 图表使用相同的 Quick/Advanced Pane 控制。分区、分组和筛选会发起新命令查询；spacing 只影响呈现。`r` 打开替换流程，可重新选择 Dataset 并在本地命令模式下编辑命令；`L` 显示诊断日志。小写 `l` 循环自定义 Timeline/Stack 的图例；大写 `L` 专用于日志。

聚焦 Dataset 图表会持续向配置命令发出所选 Dataset 协议的 chart 或 monitor 请求，不会执行 `ccusage` 的历史采集或 watch 处理。影响数据的替换请求会立即显示候选图表的标题和加载状态，不显示旧事实或“查询中”标记；同一查询的刷新失败可以保留已接受图表并显示错误，但替换查询失败绝不会显示另一选择的数值事实，只保留候选标题、范围和错误。

## 在 Dashboard 中使用自定义 Pane

使用普通的、有序 `--pane` 片段。同一数据集可出现在多个 Pane 中，但每次使用必须有相同的数据源配置。已安装 Dataset Pane 只需图表类型与 Dataset ID；任意命令仍可用于开发者集成。

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'empty' \
  --pane 'chart timeline --dataset weread' \
  --pane 'empty' \
  --pane 'animate --style rain'
```

Dashboard 预设以内置 token 消耗统计模板为基础，Dashboard 预设管理器也可以保存完整的用户配置。在浏览模式中按 `Ctrl-S` 保存，按 `P` 管理已保存的预设。预设会保留已安装 Dataset 引用、本地命令 Dataset Pane 的 argv 和命令驱动的 Overlay。它们是可信的用户本地自动化配置：加载预设会执行其中包含的命令，因此只能加载你信任的预设。预设绝不包含环境变量、凭据、结果或运行时/UI 状态。

用户预设名必须匹配 `^[a-z][a-z0-9-]*$`。用户预设可以覆盖同名内置预设：按用户优先的规则加载用户记录；删除用户覆盖后会重新显示同名内置预设。管理器在覆盖已有用户预设或删除用户预设前都会要求确认。可用 `ccuv dashboard <name>` 启动具名预设；这一封闭形式只接受 `--demo`、`--lang`、`--empty` 和 `--ccusage-bin` 作为附加选项。缺少已安装 Dataset 不会使预设变为不可用；只有预设存储不可读、格式错误或版本不支持时才显示为不可用，并阻止写入。

`dashboard --empty` 会关闭默认 ccusage Pane 及其默认数据依赖。它使用普通默认 Dashboard 布局并填入 `empty` Pane；`--grid` 或显式 layout 决定初始空 Pane 的数量和位置。它不会添加时钟。已有 `wide-clock` 和 `narrow-clock` 预设仍保留时钟 Pane。对于具名预设，`ccuv dashboard <name> --empty` 则会保留该预设的拓扑、权重、显示与节奏设置、时区、demo 和安全进程配置，只在本次启动时把所有 Pane 替换为空白 Pane；保存的记录不会变化。启用 demo 的预设加载后仍会启用 demo。

选中自定义 Dashboard Pane 后，`v` 和 `V` 可在图表、紧凑命令、完整命令、数据表和 JSON 视图间向前/向后循环。数据视图序列化 ccuv 当前本地投影的图表数据，遵守当前范围、筛选、分组、适用于非 Ranking 的粒度、Top/Other 选择和单位精度。JSON 会同时保留规范 series ID、Decimal 字符串值和本地化显示名称，不会暴露不透明的原始进程响应。

`--pane 'empty'` 是真实的临时 Pane：它参与布局、焦点、鼠标与 Tab 导航、插入、删除和复制命令序列化，但没有 Provider、调度、数据或汇总。它恰好显示两行：

```text
空白子图
双击选中，然后按 r 选择类型
```

双击空 Pane 会进入其 Dashboard 管理上下文，只显示 Dashboard 结构和位置操作，不显示图表专属设置。`r` 打开共用的替换类型选择器；`N` 和 `n` 分别打开前插和后插选择器。选择 Dataset 后，可以选择已安装 Dataset、Metric 及其声明的历史或 Monitor 图表类型，且不会显示命令路径；选择 Local command 则使用高级 Dataset ID 与 Command 字段。替换后新的 Dataset Pane 会立即发起初始查询；若失败，Pane 会显示对应数据源错误。插入操作也可以创建 Empty Pane。按 `x` 删除 Pane 会压缩其余 Pane，不会自动留下替代空位。

## 进程契约

每个物理查询执行一个命令进程：

1. ccuv 启动配置好的 argv。
2. ccuv 向 stdin 写入**恰好一个** UTF-8 JSON 请求，然后关闭 stdin。
3. 命令向 stdout 写入**恰好一个** UTF-8 JSON 响应，然后退出。
4. stderr 仅是有界诊断输出，绝不是协议数据。
5. ccuv 验证超时、退出状态、JSON、版本、ID、schema 和十进制数值。

遗留请求使用 `ccuv.custom/v1`，V2 Probe、chart、summary 和 Monitor 请求使用 `ccuv.custom/v2`。ccuv 为每次物理执行生成 `request_id`。等价的 Dashboard 进行中请求可能合并，因此该 ID 代表一次共享执行，而不是 Pane 生命周期。

每次成功的查询响应都必须自描述，携带该查询有效的 descriptor/capability、本地化数据集元数据及对应 data 或 observation；汇总事实通过独立请求返回。命令必须是无状态的：不能依赖此前的命令进程响应。

对于非固定范围且密度为 `full` 或 `detailed` 的 Ranking，除非 Ranking capability 声明 `comparison: "none"`，ccuv 会先请求当前范围，再请求紧邻且等长的上一范围。V1 保持日期 series 响应契约；V2 对两次请求都返回标量条目。ccuv 通过平铺 item ID 或分区 `(group.id, series.id)` pair 对齐，自己推导展示的绝对增长量和排名变化；上一周期缺失的条目视为新增，绝不补零。协议不应提供 delta、previous-total 或 previous-rank 字段。上一范围请求失败或不可用时，当前 Ranking 仍会显示，只是不带比较标记。`comparison: "rank"` 只将该响应用于排名变化。固定日期范围和 `all` Ranking 不请求上一范围。亚日范围锚定于同一个 aware 时刻 `T`：当前为 `[T-duration, T)`，前期为 `[T-2*duration, T-duration)`，不得分别读取当前时间而产生间隙或重叠。

仅在 Ranking 查询中，`data.series` 的每项可以提供可选 `description`、`display`、`comparison_display` 和 `link` 字段；前三者使用与 label 相同的 `{ "en": "...", "zh-CN": "..." }` 双语结构。在 `full` 和 `detailed` 密度下，ccuv 将 `description` 渲染在 Ranking 项下方，采用弱化颜色和缩进，最多换行为两行。`display` 是由 Dataset 决定、显示在 Ranking 数值列的格式化总量。V1 的 `points[].value` 仍是其计算事实来源；V2 Ranking 则以标量 `value` 作为排名、占比、比较、颜色和名次变化的权威事实。省略 `display` 时 ccuv 根据声明的 unit 格式化总量。description 可使用 `[label](https://URL)` 链接、`**粗体文字**` 与 `*斜体文字*`；ccuv 只显示 `label` 并将其作为可点击终端链接，也允许在链接文字中使用星号格式。下划线格式及其他 Markdown、HTML、格式错误链接、不支持的 URL 协议和终端控制序列都会作为安全纯文本处理。Ranking 搜索会匹配链接文字和 URL；仅 URL 命中时会追加可点击的高亮 `↗` 标记。`link` 是项目的一个绝对 `https://` URL；ccuv 在项目名后的操作区显示可点击 `↗`（`项目 | ⊞ ↗`），并在复制内容的项目名称和说明后附带该 URL。未提供 link 时不显示图标。Timeline、Stack、Calendar response 不得携带这些字段，ccuv 会拒绝；本地合成的 `Other` 项永远不带这些字段。

`probe` 是 Dataset 注册和显式刷新使用的仅元数据请求，不携带 timezone、range、query 或 summary。它不得读取业务数据、校验凭据、修改状态，或创建业务数据网关。它返回稳定 descriptor，包括声明的环境变量和图表默认值；后续 Chart 响应仍是特定查询的权威结果。

```json
{
  "protocol": "ccuv.custom/v1",
  "request_id": "probe-request-id",
  "request_kind": "probe"
}
```

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

V2 历史 chart 请求还必须携带显式顶层 `chart_kind`。Timeline、Stack、Calendar 继续使用上述含首尾日期范围和日期 points；V2 Ranking 的日期型 `d`、`w`、`mo`、`q`、`y` 周期也使用该日期范围，但响应只返回标量 value，绝不返回 points。只有 V2 Ranking 可以使用声明过的正整数 `Ns`、`Nm`、`Nh` 周期；包括 `24h`、`48h` 在内的每一种此类写法都改用 aware 时间戳，并采用精确的左闭右开语义：

```json
{
  "protocol": "ccuv.custom/v2",
  "request_id": "physical-request-id",
  "request_kind": "chart",
  "chart_kind": "ranking",
  "dataset_id": "router",
  "metric_id": "requests",
  "timezone": "Asia/Shanghai",
  "range": {
    "start_at": "2026-10-14T22:59:45+08:00",
    "end_at": "2026-10-14T23:00:00+08:00",
    "period": "15s"
  },
  "query": {"filters": {}, "group_by": "route", "top": 10}
}
```

两个时间戳都必须带时区，`start_at` 必须早于 `end_at`；Dataset 必须精确查询 `[start_at, end_at)`，不得自行重新计算“当前时间”。一个请求只能使用一套完整范围，不能混合日期与时间戳字段。每次刷新捕获新的 aware 截止时刻；只影响呈现的变更继续使用已接受范围。时间戳型 Ranking 不发起日期 summary，也不显示日期摘要；日期型 `d`、`w`、`mo`、`q`、`y` Ranking 原有的含首尾范围与 summary 保持不变。

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

成功的 V1 Chart 响应包括 `protocol`、`request_id`、`request_kind`、`dataset_id`、`status: "ok"`、`dataset`、`capabilities` 和 `data`。V2 的 Chart 或 Monitor 成功响应则包括 `descriptor`、`runtime` 和对应的 `data` 或 `observation`。成功的 Summary 响应包含 `summary.metric`。各类成功响应都可额外包含非阻断的 `warnings` 数组；每个 warning 具有开放集合的稳定 `code` 和本地化 `message`，ccuv 会显示它，同时保留成功的图表或汇总。数据集标题/描述、单位标签、维度/筛选标签和选项、系列标签、指标标签、数据源展示文本和返回消息都必须同时提供 `en` 与 `zh-CN`；ccuv 选择当前应用语言。

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

所有指标值与比较基准值都必须是普通带符号十进制表示法的十进制**字符串**。ccuv 将其解析为精确 `Decimal`。JSON 数字、空字符串、科学计数法、`NaN` 和无穷值均无效。V1 Dataset 只有一个固定单位的可相加指标，适合计数、金额和字节总量等事实。V2 还支持由 Dataset 返回精确不可相加事实的 `aggregation: "value"` Metric，语义见上文。

例如，WeRead Dataset 当前以 `Asia/Shanghai` 作为数据源日期口径。它会接受每个有效的请求时区；当请求时区不是 `Asia/Shanghai` 时，仍按上海口径成功返回数据，并附加 `timezone_not_supported` warning，而不是将成功查询变为错误。Dataset 应准确声明自己的单位与精度；WeRead 的阅读时长单位为分钟，日值和汇总值保留两位小数，汇总先聚合原始秒数再转换并舍入，因此已舍入日值的简单相加可能与汇总相差 `0.01` 分钟。

对于 V1 与可相加的 V2 日期系列响应，命令需筛选请求闭区间、应用业务规则、按请求维度聚合，并返回所请求的候选事实。V2 Ranking 改为返回数据源拥有的标量条目，并可将 `query.top` 作为请求的原始覆盖量；分区 Ranking 按上文定义把覆盖量应用到全部 Group。ccuv 执行所选协议和 Metric 允许的本地投影。不得静默替换不支持的查询。

## Capabilities 与图表

每次成功响应都返回完整、稳定的 capability manifest。它描述支持的查询面，而不是快捷键映射。v1 只提供枚举的多选筛选；不支持文本/范围/正则筛选、分页、搜索或层级筛选。不支持的分组、筛选、粒度或组合必须被拒绝，不能静默削弱或改写请求。

每个非 Ranking 图表声明允许的粒度；各图表还声明分组维度和筛选。V2 Ranking 即使携带遗留粒度元数据，ccuv 也会忽略。Timeline、Stack 接收总计或分组日期系列；Calendar 必须是未分组的每日总计。V1 Ranking 保持日期系列；V2 Ranking 则为每个平铺或分区内部条目返回一个权威标量 `value`，绝不返回 `points`。数据源特有的能力组合规则由 Dataset 自己负责——例如已声明的分组仅在特定 `range.period` 下可用时，Dataset 应返回关联到原请求的 `unsupported_query`。ccuv 原样发送用户选中的查询：不维护 Dataset 专属兼容矩阵、不替换为总计，也不改选其他时间档位。协议与投影会校验周期语法、分组、适用于非 Ranking 的粒度、筛选 ID 和已选筛选项 ID。Dashboard 只有在成功响应声明相应 capability 后才显示 `g`、`b`、`f`。V1 的本地 Top N/Other 调整只影响展示。V2 Ranking 改变 Top 时可能重新查询，因为 `query.top` 同时表达请求的数据源覆盖量；Other 仍只由实际返回的条目推导。

V1 Dataset 可以在 Ranking 响应中为官方周期汇总的每个实体提供一个位于请求 `end_date` 的点；这个遗留坐标不代表按日归因。V2 Dataset 必须改为直接返回条目的标量 `value`，不得提供 point 或伪造日期。两个版本都只有在拥有相应真实数据时，才能为 Timeline、Stack 或 Calendar 声明同一分组。

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

ccuv 会比较失败请求与已接受查询的数据影响身份。V1 与非 Ranking 日期图包含数据源、图表类型、包含首尾的范围及 `range.period`、筛选、分组和粒度。V2 Ranking 则包含数据源、显式 chart kind、Dataset/Metric ID、时区、精确日期或时间戳范围及 period 原始写法、规范化筛选、分组、分区、Top/源端覆盖和其他既有源端数据字段，但绝不包含 Ranking 粒度。同一查询的刷新失败可以保留有效事实；替换查询失败会清除数值事实，只保留本地化 Dataset 元数据以显示候选标题和范围。这一规则与 Dataset 无关，不依赖特定周期、Dataset ID 或数据源端点。空系列不是错误：返回 `status: "ok"`、空系列列表和有效的零值/`pending`/`unavailable` 汇总即可。

格式错误的输出、ID 不匹配、无效十进制、缺失本地化文本、未知协议版本、超时、启动失败，以及没有有效协议错误的非零退出都是 source/protocol failure。stderr 可以作为有界诊断展示，但绝不会作为结果解析。

仅精确等价且同时进行的请求会合并。V1 身份继续包括 argv 与执行上下文、Dataset ID、请求类型、时区、包含首尾的范围**及其 `range.period` 语义**、规范化筛选（键与选项均排序）、分组、粒度和 summary 周期/截至日期；其既有 chart kind 与呈现字段排除规则不变。V2 历史请求身份还包括显式 `chart_kind`、Metric ID、分区和影响源端覆盖的 Top。V2 Ranking 身份不含粒度，使用时间戳时则包含精确边界；时间戳按 UTC instant 规范化，因此同一时刻的不同 offset 可合并，不同秒级范围绝不会退化为同一日期 key。即使边界相同，只要 Dataset 声明的 period 原始写法不同，身份仍不同。刷新会产生新的亚日锚点与身份；比较请求使用其精确前期范围。样式、主题、密度、图例、Other、布局和 Pane 位置仍只影响呈现。v1 不支持重叠范围合并、interval/范围并集、已完成结果缓存、批处理或结果切片。

自定义 Dashboard Pane 提供 **Source**（`e`）。已安装 Dataset Pane 只编辑图表类型与 Dataset ID，然后重新验证本地安装；任意命令 Pane 通过可 Tab 导航的表单编辑 Dataset ID 与 argv。按 Enter 会验证草稿并发起查询。影响数据的替换请求会立即显示候选标题和加载状态，而不是此前图表；同一查询的刷新失败可以保留已接受事实并显示错误，替换查询失败时只保留候选标题、范围和错误。`L` 打开每个 Pane 的有界 **Logs**，`y` 可复制；小写 `l` 循环 Timeline/Stack 图例。Logs 仅包含成功查询诊断和失败信息，绝不会解析或展示协议 stdout 作为结果数据。
