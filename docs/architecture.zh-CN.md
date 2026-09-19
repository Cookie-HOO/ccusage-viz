# ccuv 如何实现

本文描述 `ccusage-viz` 已批准的目标架构。迁移仍在进行中，因此当前模块尚未完全符合下述边界。本文面向维护者与贡献者；普通使用方式请参考 README 和用户文档。

> **状态：**正在实施的目标架构。迁移阶段见[运行时架构设计](superpowers/specs/2026-09-18-runtime-architecture-design.md)。

[English](architecture.md)

## 核心术语

`ccuv` 明确区分图表类型、运行中的图表实例，以及承载实例的产品外壳。

| 术语 | 含义 |
| --- | --- |
| **Chart Definition** | 某类图表的无状态目录项。它向 bootstrap 提供稳定 ID，并引用彼此分离的配置、数据需求、结果处理、渲染、运行时设置和检查协作者。 |
| **Chart Component** | 一个运行中的图表实例。独立拥有可复用 chart payload 与生命周期状态——generation、Coverage、已接受数据、等待/运行/错误状态、语义模型和渲染内容；它接收已解析的 Host context，但不取得 Host 设置的所有权。 |
| **Host** | 运行并呈现 Component 的产品外壳。Standalone Host 承载一个 Component；Dashboard Host 在 Pane 中承载多个有序 Component。 |
| **Pane** | 一个 Component 在 Dashboard 中的位置与组合上下文。只增加几何、焦点、顺序和 Dashboard 拥有的节奏，不重新定义图表语义。 |
| **Provider** | 将逻辑请求编译为物理查询、执行查询，并返回带 provenance、resolution 和 Coverage 的规范化用量数据。`ccusage` 与 Demo 都是内置 Provider。 |

Chart Component 是 Standalone 与 Dashboard 共享的最小产品级运行单元。更小的函数和服务仍可在其下复用，但 Host 不会重新实现图表。

Definition 与 Component 的关系类似蓝图与实例：

```text
Timeline Definition
├── create(config A) → Timeline Component A → Standalone Host
├── create(config B) → Timeline Component B → Dashboard Pane 1
└── create(config C) → Timeline Component C → Dashboard Pane 3
```

即使多个 Component 使用同一 Definition 或共享一次物理 Provider 查询，它们仍拥有彼此独立的运行状态。

## 路由与 Host

路由在初始化图表运行时服务之前识别产品操作：

```text
argv
  → Route
    ├── Help / Version       → 短接
    ├── Standalone Chart     → 一个 Chart Component + Standalone Host
    └── Dashboard            → 多个 Chart Component + Dashboard Host
```

Help 与 Version 不初始化 Provider，不检查图表 TTY 条件，不进入终端输入模式，也不创建执行协调器。

Standalone 与 Dashboard 使用相同的 Chart Definition 和 Component，只由不同 Host 承载：

- **Standalone Host：**一个 Component、一份全屏组合、Standalone Controls、生命周期、检查视图和命令复制。
- **Dashboard Host：**多个 Component、Header 与 Summary、Layout 与 Weights、焦点与 Pane 生命周期、全局 Controls，以及 Dashboard 拥有的 Refresh 和 Sampling 调度器。

Dashboard Route 不调用 Standalone Route。两者都从同一 Definition 创建 Component，再交给不同 Host。

## 图表主链路

图表产品使用四个概念层级：

| 层级 | 所属概念 | 具体例子 |
| --- | --- | --- |
| **1. Route** | Route、launch request | `ccuv monitor` 选择 Standalone Monitor 操作；`ccuv dashboard` 选择 Dashboard 并描述其中的 Pane。Route 不拥有运行节奏或 Component 状态。 |
| **2. Query / Data Acquisition** | Config 中的数据范围、Query Intent、Provider、Provider Result | Monitor Config 指定 `by=model` 和 Filters；逻辑规划器结合 Host context 生成 Query Intent；`ccusage` Provider 执行查询并返回规范化累计 records。 |
| **3. Result Processing** | Processor/projector、语义 Chart Model | Monitor processing 使用 Component 保存的 previous snapshot 与 Observer 推导增量、TPM 和时间桶，再投影为 Timeline 或 Ranking Model；历史 processing 独立聚合每日 records。 |
| **4. Rendering** | Chart renderer、Chart Model、Theme、Style、Chart Render、Host composition、Painter | 选中的 Timeline 或 Ranking renderer 消费投影后的 Model。Host 加入 Controls、Header、边框等产品内容并创建完整 Frame；Painter 只比较 Frame 并写入变化行。 |

还有一些概念与这四个阶段正交：

| 概念 | 边界 |
| --- | --- |
| **Chart Definition** | 标识一种展示 Chart 并引用各层协作者的无状态目录元数据；不包含具体会话配置或运行状态。 |
| **Chart Component** | 运行实例，跨 Query、Processing 与 Rendering 独立保存 candidate/accepted 配置、事实、语义结果、generation 和 error。 |
| **Host** | 拥有节奏、输入、取消编排、几何、完整 Frame 组合和终端生命周期。 |
| **Pane** | 一个 Component 在 Dashboard 中的位置与运行上下文：identity、几何、顺序、焦点和 Dashboard 拥有的节奏上下文；不复制 Component 业务状态。 |

因此 Definition 与 Component 更接近蓝图和运行实例，不是简单的 Python 类与对象关系。Monitor 是特殊的实时 runtime/data mode，而不是另一种 Chart Definition：它的时间序列形态使用已注册的 Timeline Chart，ranking 形态使用已注册的 Ranking Chart。

```text
1. Route
2. Query / Data Acquisition
3. Result Processing
4. Rendering
```

### 1. Route

Route 选择产品操作并构造启动请求，不执行查询，也不渲染图表。

### 2. Query 与数据取得

这一层分为三个阶段。

#### 配置准备

```text
Parse → Compose defaults and Presets → Validate → Resolve startup values → Effective configuration
```

这里负责语法、参数冲突、Preset 组合、追加 Pane、Pane 所有权规则、固定日期解析和启动诊断。校验必须在依赖检查、查询、进入备用屏幕或改变终端输入模式之前完成。

#### 逻辑查询规划

共享的逻辑规划器为每个数据消费者——Standalone Component、Dashboard Summary 或 Pane Component——分别产生逻辑请求。它把 owner 已解析的 Host context、可复用 chart payload、Chart Definition 数据需求、generation、trigger 与当前 Coverage 合并为 Provider-neutral scope、缺失区间、所需 resolution 与 dimensions、Provider 选择和执行选项。两种产品形态使用同一个规划器，因此 Standalone 与 Dashboard 的缺失 Coverage 规划不会发生分歧。

Chart Definition 只声明需要什么数据，不构造 `ccusage` 命令，也不自行调用 Provider。

#### 协调与物理执行

执行协调器让 Provider 把逻辑请求编译成物理查询，施加有界并发，并把不可变结果分别交付给每个 owner。

初始优化边界刻意保持狭窄：

- 对严格相同且同时进行的物理查询去重；
- 只在产品已明确证明安全的场景共享 Monitor 原始累计快照。

协调器不跨独立 owner 合并日期范围，不合并不同 Filter，不构造字段超集，不延迟 Tick 以收集批次，不复用已完成的过时结果，不协调重叠 Source，也不拥有 Interval 语义。这不妨碍单个 owner 的逻辑规划器按产品契约合并相邻的 Coverage 缺口。

### 3. Result Processing

Provider 通过统一 envelope 返回事实数据：

```text
Normalized Result
├── records
├── provenance
├── resolution
├── Coverage
├── notices
└── provider metadata
```

Result Processing 将事实转换为图表语义。根据 Chart Definition，它可以执行筛选、历史聚合、Monitor 累计计数器求差与回退处理、观察窗口汇总、By、Top、Other 和 Summary 比较。

Query 与 Result Processing 保持分离，因为一份物理结果可以供多个配置不同的 Component 使用。Monitor Component 可以共享原始快照，但各自保留 previous snapshot、Gap、window、generation 和 error。

### 4. Rendering

```text
Semantic Chart Model
  → 内置图表 renderer
  + 声明式 Theme / Style
  → Chart Render
  → Standalone 或 Dashboard composition
  → 完整 Frame
  → Terminal Painter
```

Renderer 不查询数据，也不直接写 stdout。Status、Controls、Notices、设置、检查内容和图表正文会被组合为完整逻辑 Frame。Painter 比较完整 Frame，只写入变化的终端行；完整逻辑重绘不代表无条件清屏。

Plotext 使用进程级全局状态，因此其渲染位于串行 adapter 之后。Query 是当前管线中唯一必须异步执行的阶段：Provider 工作通常耗时数秒，而当前 Processing 与 Rendering 都是毫秒级操作。因此，Processing 保持为同步且隔离的语义转换，Rendering 通过串行 adapter 同步执行。只有后续 profiling 证明渲染明显影响输入响应时，才在不改变 Component 与 Host 语义的前提下把现有渲染边界移入单个串行 worker。

## 运行时状态

Host 与 Component 通过 Action 和 Effect 协作：

```text
Action → reduce(state, action) → new state + effects
```

Action 包括 Tick、手动刷新、暂停/继续、Resize、输入、设置变化、查询成功、查询失败和防抖到期。Effect 包括异步提交查询、安排防抖、重建调度器、复制、重绘和退出。已接受的查询 completion 会同步处理为语义模型，再通过 Plotext 串行 adapter 同步渲染，之后才组合完整 Frame。

每个拥有数据的 Component 都维护独立的生命周期 envelope：

```text
Component State
├── candidate chart payload + resolved Host context
├── accepted data
├── data generation + processing/render revision
├── Coverage
├── active operation + subscription
├── debounce handle
├── pending trigger
├── observer
├── accepted success time
└── last error
```

### 运行时身份与结果接受

四种身份分别表达产品所有权、数据意图、逻辑执行和共享物理工作，不能相互替代：

| 身份 | 含义 | 设置者 | 变化时机 |
| --- | --- | --- | --- |
| **Owner ID** | 结果属于哪个 Component 或其他数据 owner | Host 在创建 owner 时设置 | owner 终止并创建新 owner 时变化；移动或重新配置 Pane 不改变它 |
| **Generation** | owner 当前数据意图的版本 | 已提交配置需要 accepted facts 与 Coverage 尚不能满足的数据时，由 Component 更新 | 数据需求变化时递增；重绘、本地重新处理、周期刷新和手动刷新不改变它 |
| **Operation ID** | 一个 owner 的某一次逻辑执行 | Lifecycle coordinator 真正提交工作时分配 | 每次 Startup、Periodic、Manual、Configuration、Resume 或重试提交都变化，同一 Generation 内也不复用 |
| **Subscription ID** | 一个 owner 对某项 in-flight 物理查询的一次需求 | Execution coordinator 将 operation 挂接到物理工作时分配 | 每次挂接或重新挂接都变化，即使可以复用已有物理查询 |

只有 Owner ID 与当前 owner 匹配、Generation 与当前数据意图匹配、Operation ID 仍是当前 active operation，且 Subscription 尚未 detach 时，completion 才能修改 Component 状态。进入 stopping 后拒绝所有 completion。被拒绝的 completion 不更新数据、Coverage、error、加载占位、pending intent，也不能清除更新的 active operation。

Generation 不是查询计数器。例如，同一配置的一次周期刷新与稍后的手动刷新使用同一 Generation，但各自获得不同 Operation ID，从而防止迟到的周期 completion 被误认为当前手动 operation。相反，修改 Theme 时事实仍然有效，因此 Generation 与当前 subscription 均不变化；把日期范围扩大到 accepted Coverage 之外时，Generation 递增、过时工作 detach，受影响的数值显示 `??`。

Subscription 与物理查询相互独立。两个 Pane 请求相同物理数据时，各自拥有 Owner、Generation、Operation 和 Subscription，Coordinator 可以只执行一次物理查询。某个 Pane 修改配置时只 detach 自己的 Subscription；只有最后一个 subscriber detach 后，Coordinator 才尝试取消物理工作。稍后的手动请求可以用新的 Operation 与 Subscription 挂接到仍可安全复用的物理查询，但旧 subscription 永远不会重新有效。

数据相关调整立即递增 Generation，并 detach 过时 effect。数据及 Coverage 只为当前 Generation 原子接受；过时 success 与 failure 都不更新状态。Theme/Style、viewport 与仅 transient 的变化递增独立的 render revision。可以由 accepted facts 计算的变化只递增 processing/render revision，不改变 data Generation。本次重构不引入已完成结果缓存。

主动 detach 不是业务错误。配置替换、Pause 取消自动工作、owner 删除和 shutdown 都应抑制已 detach 的 completion。Pause 取消自动的 Startup、Periodic 与 Resume 工作并清除周期 backlog，同时仍允许显式手动刷新和已提交配置产生的一次性补齐；它们完成后不会恢复周期调度。Shutdown detach 所有 subscription，清除 pending 与 debounce 状态，拒绝后续所有 completion，再按顺序关闭 runtime 与终端资源。

Refresh、Sampling、debounce、手动刷新、继续和已提交配置工作保持为可区分的触发来源。固定调度基线不因查询耗时、成功、失败、手动刷新、暂停或继续而移动。慢 Component 不会为同一 generation 重叠执行同一管线阶段；等价的等待机会只在各自 trigger kind 内合并。

异步 Query worker 通过一条串行 runtime queue 返回不可变 completion action。只有 runtime owner 可以修改状态、同步处理已接受事实、串行渲染图表、组合 Frame 与绘制。Render revision 仍用于区分连续可见状态，但没有性能数据时不引入 render worker 或 render completion queue。关闭时依次停止接纳新工作、分离或取消工作、抑制延迟 completion、停止绘制，最后恢复终端状态。

Historical no-Watch 与 Historical Watch 使用相同的启动、查询、接受、处理、Frame 和 Painter 路径，只是在第一份已接受 Frame 后退出。

## 内置能力 Registry

实现使用私有、静态的内置能力 Registry：

- Provider Registry
- Chart Registry
- Theme Registry
- Style Registry

Registry 显式注册能力、拒绝重复 ID、保持确定性顺序，并在解析或运行前冻结。只有应用 bootstrap 会组合生产 Registry。

这些 Registry 是用于组合当前内置应用的私有依赖倒置接缝，不是公开 API。

### Provider

初始内置 Provider：

- `ccusage`：封装查询规划、安全子进程执行、Schema 校验和规范化；
- Demo：提供确定性的进程内记录，不检查外部依赖。

Provider 代码不导入图表或展示代码。图表代码不调用 Provider，也不读取外部存储。

### Chart

每种内置图表拥有一个 Definition，并可创建任意数量的 Component。Bootstrap 使用彼此狭窄的分层协作者组装 Definition：配置描述、数据需求描述、processor/projector、renderer、运行时设置描述和检查描述。Query、processing 与 presentation 只导入自身需要的协作者 contract，不导入完整 Definition。

### Theme 与 Style

Theme 与 Style 是声明式展示能力。Theme 提供语义颜色角色与调色板，Style 描述兼容的视觉语法。两者都不读取 Provider 数据、不改变 Data Scope、不发起查询、不控制 TUI 生命周期，也不写入终端。

## 未来的 Animation 能力

Animation 是独立资源类型，不是 Chart 变体，也不是所有图表默认经过的后处理阶段。

未来的 Animation 资源可以：

- 通过 Standalone Host 运行；
- 占用 Dashboard Pane；
- 在不查询用量数据的情况下更新 Frame。

Chart Component 需要 Query 与 Result Processing；Animation Component 不需要。两者未来可能共享 Host、viewport、Frame、input 和 Painter 基础设施，但应等两类真实实现都存在后，再提取共同 Hosted Component 协议。

当前架构让 Route dispatch 与 Host/content composition 保持可扩展，但不添加无实现的 Animation route case 或资源 discriminator。Animation Schema、资源预算、帧节奏和 Dashboard Header 集成不属于当前设计。Header 品牌、静态 Logo 与动画仍是彼此独立的未来设计问题。

## 依赖方向

```text
CLI / TUI Driver
       ↓
Bootstrap and use cases
       ↓
Runtime engine
   ↙    ↓     ↘
Config Query Presentation
   ↘    ↓     ↙
       Core
       ↑
Capability contracts
       ↑
Built-in implementations
```

规则：

- Core 只导入标准库。
- Configuration 依赖 Core 值与能力 ID，不依赖 TUI 或 Provider adapter。
- Query 依赖 Core 与 Provider contract，不依赖 CLI、TUI 或 rendering。
- Presentation 依赖 Core 与 chart/theme/style contract，不依赖 Provider adapter。
- Built-in 实现 capability contract。
- Bootstrap 是唯一允许导入所有 built-in 的生产 composition root。
- library module 不导入 CLI parsing。
- Dashboard 不导入 Standalone 私有函数。
- Provider 不导入 Chart；Chart 不导入 Provider。

Import-boundary 测试强制执行这些规则。
