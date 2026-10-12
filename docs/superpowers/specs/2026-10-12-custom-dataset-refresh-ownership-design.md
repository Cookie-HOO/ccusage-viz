# Custom Dataset 刷新信息接管设计

## 目标

允许 Custom Dataset 明确接管 Ranking 和 Monitor 的变化信息。接管后，ccuv 直接展示 Dataset 返回的状态与适用文案，不等待或计算这些信息，也不为 Ranking 变化展示请求前一期数据。

接管是完整的信息提供责任，而不是对单个字段的可选覆盖。Dataset 缺少必填信息时，ccuv 尽量展示已有有效信息，并在所属图表内常驻报错；不能静默回退到本地计算。

Monitor 的接管不要求 Dataset 记录历史。Dataset 提供本次观测，ccuv 继续轮询、记录本次会话的 observations，并供所有已有 Monitor style 绘制或累计。

## 范围与非目标

本次只扩展 Custom Dataset 的 Ranking / Monitor capability、响应解析、处理和呈现，覆盖 Standalone 与 Dashboard。

不改变：

- 原生数据源的 Ranking / Monitor 行为。
- 未声明接管的既有 Dataset 行为，包括请求策略和错误处理。
- 独立 summary 查询。
- 实际数值驱动的排序、Top 和正常的 Other 处理。
- Monitor 的固定业务窗口、有效观测保留范围与现有累计窗口规则。

不增加：

- Monitor 历史回填协议、持久化或重启恢复。
- 为每个折线点或累计桶新增活动图标、排名箭头或趋势着色。
- Dataset 对源端业务语义一致性的证明义务。
- Timeline / Calendar / Stack 历史图的接管状态字段。

## 当前实现中的两类信息

历史 Ranking 的相邻刷新标记与前期对比列是不同机制：

- 活跃标记、刷新排名方向、刷新数值方向来自刷新状态。
- 前期对比列依赖上一等长周期的 chart 数据；`comparison_display` 当前只替换具备非零可计算差额的文案。

本设计的 Dataset 接管覆盖上述变化展示，而不只是刷新标记。因此接管模式取消 Ranking 前期 comparison 请求，并解除 `comparison_display` 对本地比较结果的依赖。

Custom Monitor 已经接受 Dataset 给出的固定窗口 observation；首个有效 observation 的数值不需要像原生累计计数器 Monitor 那样等待两次快照求差。不能把扩展描述成给 Custom Monitor 新增数值 baseline，也不能声称现有 Custom Monitor 已有完整的三状态自动推导。默认模式严格保留实际实现。

## 协议

### Capability 声明

在每个 Metric 的 Ranking 或 Monitor capability 中增加：

```json
"refresh": "dataset"
```

允许值为 `"ccuv" | "dataset"`，省略等价于 `"ccuv"`，表示沿用当前实现，不承诺新增任何默认推导能力。

该声明属于 capability，不属于 CLI 覆盖或运行时根据某个实体字段猜测的模式。Ranking 与 Monitor 可以分别声明。协议中同名字段根据位置区分：capability 的 `refresh` 是 owner 枚举，实体的 `refresh` 是状态对象。

### 实体状态

```json
"refresh": {
  "active": true,
  "rank_change": "up",
  "value_change": "unchanged"
}
```

- `active`：JSON boolean。
- `rank_change`、`value_change`：`"up" | "down" | "unchanged"`。
- 两个 change 只表示方向，不表示具体幅度。
- `false`、`"unchanged"` 和数值字段里的零都是有效值。
- 缺失、null、错误类型或不支持的枚举值不能等价于不活跃、不变或零。

Dataset 对方向与实际数值、排序、活跃之间的业务一致性负责。ccuv 只校验结构、类型、枚举与完整性，不纠正互相矛盾的有效字段。

### 字段位置和必填清单

| 场景 | 接管状态位置 | 必填信息 |
| --- | --- | --- |
| 历史 Ranking | 每个真实 `data.series[]` 的 `refresh` | 原有实体标识、数值等基本信息；`active`、`rank_change`、`value_change` |
| Monitor 分组 | 每个 `observation.groups[]` 的 `refresh` | 原有实体标识、数值等基本信息；`active`、`rank_change`、`value_change` |
| Monitor 未分组 | `observation.refresh` | 原有 `end_at`、`total` 等基本信息；`active`、`value_change` |

Monitor 未分组不要求 `rank_change`；即使提供也不显示无意义的单项排名变化。分组 Monitor 不额外要求 observation 总计的 refresh 状态。

必填判断针对响应中的真实实体，不因 Top、当前 style、密度、终端宽度或当前是否可见而变化。合法的空实体列表没有虚构的逐项状态要求。所有原有可用性条件仍有效。

ccuv 合成的 `Other` 没有 Dataset 所提供的独立身份，不要求 Dataset 为其提供状态或 `comparison_display`，也不为其伪造或汇总这些展示字段。

### `comparison_display`

保留 Ranking series 上现有的本地化字段结构，不改名、不新增别名：

```json
"comparison_display": {
  "en": "+120",
  "zh": "+120"
}
```

接管模式下：

- Ranking capability 的 `comparison: "full"`：每个真实实体必须提供有效 `comparison_display`，不变可明确返回 `"0"`。
- `comparison: "rank" | "none"`：不要求也不显示数值对比文案。
- 在允许显示数值对比列时，直接使用当前响应文案，不要求前值、非零差额或前期 comparison 响应。
- 缺失时留空并报错，不显示推导出的数字、`New` 或默认零。
- `rank` / `none` 对原有前期对比列的限制仍然适用，不取消本次三个状态字段的提供责任。
- 原有前期排名方向列如可见，使用 Dataset 的 `rank_change`，不重新计算前期排序差值。

默认模式下，`comparison_display` 的现有使用条件不变。

本次不将 `comparison_display` 扩展为 Monitor 必填字段，也不为 Monitor 新增数值对比文案列。

## Ranking 行为

### 默认模式

保留现有 primary / comparison 请求规划、刷新状态计算、列可见性与文案处理。

### Dataset 接管

- 不发起为该 Ranking 变化展示服务的前期 chart 请求。
- 不推导排名方向、数值方向或活跃状态。
- 不使用缓存的 comparison 响应或旧刷新状态补充缺失信息。
- 首次有效响应即可展示 Dataset 提供的状态与适用文案。
- 不以“没有 comparison response”为由整体隐藏已提供的接管比较信息。
- 密度、宽度等正常几何约束仍决定可见布局；隐藏字段仍接受完整性校验。
- 不因为某个字段缺失而隐藏同一行的其他有效字段。
- `value_change` 不改变数值、排序或 `comparison_display` 的字面内容。
- `rank_change` 不重新排列项目；排序仍由原有值和排序方向决定。

普通 summary 是独立功能，不因 Ranking 接管而取消。

## Monitor 的职责边界

### Dataset 负责

- 按现有请求回答截止时刻对应的固定窗口 observation。
- 提供本次有效数值及完整的适用接管状态。
- 决定状态的业务比较基准。

Dataset 不必保存历次 observation，也不必在首屏返回历史。

### ccuv 负责

- 继续采样和接受 observations。
- 在当前会话内保留有效观测与随附字段。
- ranking/list 展示最新有效观测及其已有状态。
- timeline、line、points 等已有时间序列 style 使用会话观测记录。
- cumulative-bars 按现有累计与非重叠窗口规则处理记录，不能把重叠业务窗口重复相加。
- 切换 style 复用已记录数据，不再次求差、不改变数值语义。

首条 observation 返回 `120`，ccuv 展示并记录 `120`，不等待下一条 `150` 后改成 `30`。数值有效但状态缺失时，仍记录数值并允许绘图、累计。

`active: false` 不丢弃观测；`value_change: "down"` 不把数值取负。展示字段不参与计算。

没有观测的历史区间保留缺口，不补零、不复制当前值填满过去。重启后仍按现有行为从新的会话记录开始。

所有 style 都支持接管观测的记录、绘制和相应累计，并展示所属图表的协议错误。本次不为不具备状态标记的 style 强行增加新视觉。

## 不完整与无效响应

### 可局部恢复的问题

缺少必填状态、错误的状态类型或枚举、缺少适用的 `comparison_display` 等，属于接管协议错误，但不直接拒绝整个响应。

- 独立保留每个有效字段。
- 无效字段按不可用处理，对应展示留空。
- 不回退计算，不补发 comparison 请求，不从上一响应填充字段。
- 产生包含实体身份与字段路径的结构化错误信息。

### 基本事实损坏

尽量展示的前提是能够安全识别数据：

- JSON 不可解析、身份或请求不匹配等，不能作为当前有效响应接受。
- Monitor 缺少有效 `end_at` 时，不能记录此次 observation，也不能用接收时间冒充源端时间。
- 某项基本数值无效、其他项可用时，保留可安全识别的有效项；无效项不参与数值图形或运算。
- 缺失数值不能变成零、沿用旧值或变成已知事实。局部缺口不得生成依赖完整数据的伪造占比、Other 或总计；无法由仍有效的事实确定的派生展示保持不可用。
- 整体无法安全接受时，保留上一份已接受画面，并明确显示错误；它不是把旧字段混入新响应。

现有请求身份、generation、取消和过期 completion 检查优先于局部恢复。被拒绝的过期响应不能更新画面、历史或清除当前错误。

## 常驻错误提醒

错误属于图表数据状态，不是临时 toast：

- Standalone 在所属图表固定错误区显示。
- Dashboard 在对应 Pane 显示，不占用或覆盖其他 Pane 的错误状态。
- 提示必须能识别缺失或无效的实体字段；多个问题汇总显示总数与代表性明细，遵守终端宽度限制。
- 使用可本地化消息，并对 Dataset 实体文字应用现有终端安全处理。
- 不因时间、重绘、style、密度或 Top 变化而消失。
- 新的部分有效响应更新有效内容与错误清单，不清除仍存在的问题。
- 后续被接受的完整有效响应自动解除当前错误。
- 请求失败、过期结果或纯本地重投影不能被当成完整恢复。
- 历史某次状态缺失不要求后续补齐；新响应完整后可以解除当前错误，不追溯修改历史观测。

切换数据上下文时，沿用现有安全预览与接受机制。旧快照仍可见时其错误也不能被误清除；新上下文的结果接受后，展示该上下文自己的数据与错误。

## 内部设计

### 协议边界

在 Custom 模型中表达 capability owner、实体 refresh 字段以及可局部恢复的校验问题。严格区分有效的 false/零/unchanged 与不可用值。

解析层负责字段校验与问题路径，不负责计算业务状态。局部恢复限制在接管协议路径，不能顺带放宽旧 Dataset 的错误规则。

### Component / projection 边界

- capability owner 决定是否规划 Ranking comparison 查询。
- 统一投影提供 renderer 所需状态及文案，renderer 不自行选择 owner。
- 接管模式阻断旧 comparison 和本地刷新计算的注入路径。
- 接受有效数据时一并保存其错误状态；错误不能只存在于一次 render 调用。
- Monitor 保存有效 observation，状态不干预数值历史和累计处理。
- 外观调整只重投影已接受事实，不重新校验成另一种 owner 或触发比较查询。

实现应沿现有协议模型、CustomComponent、CustomMonitorComponent 与共享呈现边界扩展，不增加独立的第二套图表运行时。

### 呈现边界

保持现有图表布局与主题。共享状态模型区分不活跃、不变、缺失；缺失不渲染伪造标记。原生适配器与默认 Custom 路径维持原行为。

常驻协议错误与有效图表可以同时呈现，Standalone 和 Dashboard 均需预留所属表面的错误行预算。

## 验证

- 未声明接管的 Dataset 行为、请求策略、字段校验不变。
- 原生 Ranking / Monitor 无回归。
- capability 枚举与实体状态对象按位置解析；不支持的 owner 不被猜测为某种模式。
- 接管 Ranking 首屏完整时直接显示，不查询前期；独立 summary 不受影响。
- full/rank/none 的文案必填与列限制正确，窄宽度和隐藏列不放松数据契约。
- 三个状态可独立呈现，语义冲突不产生错误。
- false、数值零和 unchanged 有效；null、缺失、非法枚举和错误类型形成字段问题。
- 缺字段的新响应不继承旧字段或旧 comparison 数据。
- comparison_display 可直接显示零或其他文案，不依赖计算差额。
- 合成 Other 不伪造状态，不承担真实实体的必填要求。
- Monitor 未分组不要求排名方向；分组要求各实体完整状态。
- Monitor 数值有效、状态损坏时仍能记录并在所有 style 正常使用有效观测。
- 不以 active 或方向字段改变数值、排序、丢弃观测或修改累计。
- 首次观测不虚构历史；重叠窗口不重复累计。
- 基本事实损坏时安全局部恢复；不能恢复的整体错误保留旧画面并提示。
- 错误跨多个周期、style 与密度切换持续存在；完整有效结果解除。
- 过期、失败或身份不符的响应不能清除错误或污染 Monitor 历史。
- Standalone 与 Dashboard 各自正确显示并预算常驻错误，Pane 间隔离。

## 文档更新范围

实现时更新中英文 Custom 协议、Dataset 开发指南及相关用户说明：声明 owner、列出必填字段、解释部分展示与常驻错误、说明 Monitor 无历史提供义务。默认路径与接管路径必须分别描述，避免继续将刷新标记、前期比较与 Monitor 累计快照求差混为一谈。
