# V2 Ranking 标量结果与亚日周期设计

## 状态与目标

本设计依据已确认的讨论边界，等待用户审阅后进入实施计划。

对尚未推广的 `ccuv.custom/v2` 做破坏性 Ranking 契约升级：排行项直接返回范围内的权威数值，不再使用带日期的 points，不再依赖 granularity。仅 Custom Historical Ranking 新增 Dataset 自主声明的秒、分钟、小时周期。同步对当前三个已注册插件做最小协议适配。

“不需要时间”指排行项不需要时间坐标，不是删除查询统计范围、刷新时间或前期比较。

## 范围

包含：

- V2 Custom Ranking 的平铺与 partition 响应、解析、投影、比较、请求身份、配置和持久化。
- 内置 Ranking 的模型、参数和调用链审查及回归：条目无时间坐标、没有 granularity。
- Custom Ranking 的正整数 `Ns` / `Nm` / `Nh` 周期及精确范围。
- weread、router、github-tools 的协议迁移、测试、文档、构建和本地注册快照更新。
- CCUV 开发者指南、示例和受影响的测试 fixture 更新。

不包含：

- Timeline、Stack、Calendar 的亚日精度、granularity 或 points 改造。
- Monitor 的采样窗口、协议或业务逻辑变化。
- 内置 Ranking 的秒、分钟、小时周期。
- 插件新增指标、周期、数据源、聚合算法、筛选或分组行为。
- 任意不透明 period ID，例如 `billing_cycle`。
- 远端发布、推送或签名 catalog 发布。
- V1 协议契约变更；共享代码修改不得导致 V1 回归。

## 当前实现核对

内置 `RankingConfig` 已无 granularity，`RankingEntry` 已只包含聚合 usage，没有逐项时间坐标。保留其查询 DateRange 和 summary，不把源记录的时间误判为需要删除的排行项时间。

Custom Ranking 目前复用 `CustomSeries.points`、`CustomChartProjection.days`、时间分桶和 granularity 校验。granularity 也进入请求 key、结果匹配、重新查询判断及 defaults。因此需要独立 Ranking 解析与投影分支，不能只删除 wire 字段。

已完成的 partition 实现使用 `data.groups[].series[]`；内部条目与平铺 `data.series[]` 共用 dated series。这次对两种形态统一升级。

## V2 Ranking 请求

明确发送顶层 `chart_kind: "ranking"`，供多图类型 Dataset 判别请求和响应形态。V2 其他历史图也应明确其现有 chart kind，而不是依靠 group_by 推断；不改变其结果契约。

日及以上周期保留现有请求范围：

```json
{
  "protocol": "ccuv.custom/v2",
  "request_id": "pane:1",
  "request_kind": "chart",
  "chart_kind": "ranking",
  "dataset_id": "example",
  "metric_id": "requests",
  "timezone": "Asia/Shanghai",
  "range": {
    "start_date": "2026-10-13",
    "end_date": "2026-10-14",
    "period": "2d"
  },
  "query": {"filters": {}, "group_by": "route", "top": 10}
}
```

亚日周期使用互斥的 timestamp 范围：

```json
{
  "protocol": "ccuv.custom/v2",
  "request_id": "pane:1",
  "request_kind": "chart",
  "chart_kind": "ranking",
  "dataset_id": "example",
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

timestamp 必须 aware，起点早于终点，范围为 `[start_at, end_at)`。边界权威，Dataset 不根据自己的当前时间重算。日期范围保持两端包含的原有语义。一个请求必须有一套完整范围，不能混用两种字段。

## 周期与刷新

Ranking capability 可以声明：

```json
{
  "ranking": {
    "periods": ["15s", "90s", "10m", "45m", "1h", "6h", "1d", "all"],
    "group_by": ["route"]
  }
}
```

- `s` 是秒，`m` 是分钟，`h` 是小时；值为任意正整数。
- Dataset 拥有候选集合及顺序。CCUV 不插入、排序或换算声明的字符串；`90s` 不自动改名成 `1m30s`。
- `p/P` 使用当前 chart capability 的声明，不能被陈旧 pane 的 metric_periods 覆盖。
- 未声明 periods 时保持既有 fallback；不新增 CCUV 内置亚日档位。
- 现有 `d/w/mo/q/y/all` 语义不变，包括自然周期规则和 `all` 的既有限制；`1d` 不变成最近 24 小时。
- 每次亚日 primary 查询只捕获一个 aware 锚点 T：范围为 `[T-duration, T)`。
- refresh 产生新锚点，不复用启动时刻；展示变更不能偷偷移动已接受的查询范围。
- 解析允许新单位的范围限定在 V2 Custom Ranking；不能通过放宽全局 parser 意外开放其他图或内置 Ranking。
- 配置、复制命令和 preset 往返保留声明的 period 字符串。相对范围恢复时重新计算锚点；固定范围保留原边界。
- 本次不增加专门的 timestamp CLI 边界参数；亚日入口为已存在的 period 选择。

## Ranking 标量响应

保留 wire 容器命名 `series`，仅改造其条目契约，不做无关重命名。

```json
{
  "data": {
    "series": [
      {
        "id": "route-a",
        "label": {"en": "Route A", "zh-CN": "路由 A"},
        "value": "185.2"
      }
    ]
  }
}
```

- 每个条目必须有 decimal string `value`，继续使用 Decimal 处理。
- 不接受 points 作为新 V2 Ranking 数值来源；混合 value 与 points 拒绝，避免双重解释。
- 条目不要求 date 或 timestamp。CCUV 不构造伪日期、不把 value 包装回 dated point。
- Dataset 对请求范围负责：求和、P95、增长或其他现有算法由 Dataset 执行。CCUV 不从时序点重算。
- 既有 description、display、comparison_display、link 保留其校验与展示规则。
- 空列表表示有效范围无排行项，不凭空造零。
- Metric 的 aggregation 继续描述其现有指标语义，不删除、不重新定义；Ranking 不再用它决定是否汇总时间点。
- 排序、Top、Other、份额等现有跨条目处理保持原行为，不借此次迁移修改非可加指标的 UI 规则。

在内部模型上，将 V2 Ranking entry/data/projection 与 dated historical series 区分。共享元数据或展示辅助逻辑可以复用，但 Ranking 不得通过伪日期、默认 day 或单元素时间轴保持旧依赖。

## Partition 保留

```json
{
  "data": {
    "groups": [
      {
        "id": "logical-a",
        "label": {"en": "Logical A", "zh-CN": "逻辑 A"},
        "series": [
          {
            "id": "real-a",
            "label": {"en": "Real A", "zh-CN": "真实 A"},
            "value": "185.2"
          }
        ]
      }
    ]
  }
}
```

- 外层 group 及其元数据结构不变；每个内层条目改为 scalar value。
- groups 与 series 互斥，按实际 partition 查询验证响应形态。
- 保留 partition capability、维度目录、defaults、请求、CLI、preset 与合法组合规则。
- `g/G` 仍是 partition 控制，`b/B` 仍是排行维度；去掉 granularity 不删除 partition。
- 保留 Dataset 的外层顺序，每组内独立排序、Top N、Other、比例和缩放。
- 保留 max_items 现有跨分区计数规则、组内 ID 唯一性，以及不同组可以有相同条目 ID。
- 保留搜索不重排、不重新计算份额及缩放的规则，以及滚动、sticky heading、复制和 grouped Other。

## 移除 Ranking granularity

仅针对 Ranking：

- capability 中不再要求 granularities；携带时不解析、不校验、不生效。
- defaults 中 granularity 携带时不解析、不校验、不生效。
- CCUV 请求不发送 query.granularity。插件接受旧请求携带此字段时忽略它。
- 请求 key、结果匹配、重新查询判断、默认配置和 Metric 切换规范化不受 Ranking granularity 影响。
- 旧 preset 中的 Ranking granularity 忽略，而不是用其值阻止载入；非 Ranking 维持原校验。
- 新生成的 Ranking 专属配置和导出不再表达时间粒度。

Timeline、Stack、Calendar 的 granularity 按原契约解析。V1 保持旧协议。

## 比较、请求身份与 summary

亚日比较与 primary 共用锚点 T，前期为 `[T-2*duration, T-duration)`，不得分别读取当前时间导致间隙或重叠。保留 comparison full/rank/none、密度触发以及固定范围与 all 的既有禁用规则。

平铺匹配 item ID；分区先匹配 group ID，再匹配组内 item ID。旧期缺失不能当作零。数值变化和名次变化读取 scalar values。

请求 key 和完成结果匹配包括真实范围、period、timezone、Dataset/Metric/source、filters、group_by、partition_by，以及现有其他数据相关字段；不包括 Ranking granularity。timestamp 按 UTC instant 规范化，同一时刻的不同 offset 表达不能形成不同身份。不同秒级范围不能退化成相同日期 key。

summary 保持日期协议，不在本次扩展 timestamp summary。亚日 Ranking 不发送用日期截断伪造的 summary 请求，不展示过期日级 summary；现有日级 Ranking summary 不变。三个插件无需新增 summary 行为，因为不会新增亚日 periods。

## 插件最小迁移

已注册源码：

- weread：`/Users/bytedance/Projects/go/ccuv-dataset-weread`
- router：`/Users/bytedance/Projects/go/ccuv-router-dataset`
- github-tools：`/Users/bytedance/Projects/github-projects`

处理原则：

1. 保持现有指标、periods、数据调用、计算结果、过滤、分组、Top 和展示元数据不变。
2. Ranking 现有范围聚合结果直接输出 value；若已有多点可加结果，在原本负责查询结果组装的位置产生同值聚合，而不是新增查询算法。
3. 移除 Ranking granularities 声明与请求 granularity 校验；非 Ranking 保留。
4. 用明确 chart_kind 区分响应，尤其 weread 的多图指标；原有数值来源保持不变。
5. Router 不新增 requests/P95 Historical Ranking；quota all 原业务不变。
6. weread、github-tools 不声明自身不支持的秒/分钟/小时。
7. 测试断言迁移后的 value 与旧结果相同，并验证其他图/Monitor 不变。
8. 构建注册路径指向的本地二进制，成功 Probe 后通过 CCUV 的注册刷新流程更新快照，不手改注册 JSON 掩盖协议失败。
9. 保留插件仓库未提交修改，不覆盖 GitHub catalog 数据或 Router 现有业务改动。只提交本任务相关文件或 hunks。
10. 不调用额外付费/真实业务查询验证；真实查询失败不能用零替代。协议集成优先用 fixture、fake server 与已有测试。

## 验证门

- V2 Ranking 平铺/分区 value 成功；points-only、双数值来源、非法 decimal、重复 ID 和错误形态拒绝。
- Ranking gran 字段缺失及任意遗留值均不影响解析；其他图仍按原要求校验。
- 内置 Ranking 无 gran、无条目时间，原排序、比较与 summary 回归通过。
- `15s/90s/10m/45m/1h/6h` 声明、defaults、循环、刷新、跨午夜、时区/DST instant 计算、比较锚点和 preset 往返通过。
- 新单位在非 Custom V2 Ranking 路径拒绝；日级自然周期不变。
- 不同精确范围不合并，相同 UTC 边界可合并；Ranking gran 不影响身份。
- partition 全链路行为保留，特别是 independent Top/Other、比较作用域、搜索、复制和 sticky heading。
- 三个插件旧逻辑结果一致，weread 其他图和 Router Monitor 回归通过。
- CCUV 完整测试及现有 lint；三个 Go 仓库各自 `go test ./...`。
- 三个注册二进制 Probe 成功，注册快照不再携带 Ranking gran 声明；其他能力不变。

## 与并行工作的边界

当前工作树已有不属于本任务的计划文件，Router 和 GitHub 插件也已有未提交修改。开始实施前重新检查 git status/log；以最新 partition 提交为基线，不回滚其代码。修改重叠时进行小范围合并并补 regression，不改动独立的预取或排名变化指示器任务。
