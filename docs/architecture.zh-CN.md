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

Plotext 使用进程级全局状态，因此其渲染位于串行 adapter 之后。渲染工作在 reducer 与终端输入循环之外执行；带 generation 的完成结果返回 `ChartRender`，经接受后再参与 Frame composition。

## 运行时状态

Host 与 Component 通过 Action 和 Effect 协作：

```text
Action → reduce(state, action) → new state + effects
```

Action 包括 Tick、手动刷新、暂停/继续、Resize、输入、设置变化、查询成功、查询失败和防抖到期。Effect 包括提交查询、有界且带 generation 的结果处理、安排防抖、重建调度器、复制、重绘和退出。结果处理与串行 Plotext 工作在 reducer 和终端输入循环之外执行。

每个拥有数据的 Component 都维护独立的生命周期 envelope：

```text
Component State
├── candidate chart payload + resolved Host context
├── accepted data
├── data generation + render revision
├── Coverage
├── query / processing / rendering activity
├── debounce handle
├── pending triggers by kind
├── observer
├── accepted success time
└── last error
```

数据相关调整立即递增 generation，并分离过时 effect。数据及其 Coverage 只会为当前 generation 原子接受；过时交付不会更新任何一项。Theme/Style、viewport 与仅 transient 的变化递增独立的 render revision。本次重构不引入已完成结果缓存。

Refresh、Sampling、debounce、手动刷新、继续和已提交配置工作保持为可区分的触发来源。固定调度基线不因查询耗时、成功、失败、手动刷新、暂停或继续而移动。慢 Component 不会为同一 generation 重叠执行同一管线阶段；等价的等待机会只在各自 trigger kind 内合并。

Worker 通过一条串行 runtime queue 返回不可变 completion action。只有 runtime owner 可以修改状态、组合 Frame 与绘制。Plotext 串行层对每个 Component 只保留最新的排队 render revision。关闭时依次停止接纳新工作、分离或取消工作、抑制延迟 completion、停止绘制，最后恢复终端状态。

Historical no-Watch 与 Historical Watch 使用相同的启动、查询、接受、处理、Frame 和 Painter 路径，只是在第一份已接受 Frame 后退出。

## 内置能力 Registry

实现使用私有、静态的内置能力 Registry：

- Provider Registry
- Chart Registry
- Theme Registry
- Style Registry

Registry 显式注册能力、拒绝重复 ID、保持确定性顺序，并在解析或运行前冻结。只有应用 bootstrap 会组合生产 Registry。

这些 Registry 是内部依赖倒置接缝，不是受支持的第三方 Python API。当前架构不实现插件发现、manifest、安装、包扫描、动态 Python import、沙箱或公开能力协议。

### Provider

初始内置 Provider：

- `ccusage`：封装查询规划、安全子进程执行、Schema 校验和规范化；
- Demo：提供确定性的进程内记录，不检查外部依赖。

Provider 代码不导入图表或展示代码。图表代码不调用 Provider，也不读取外部存储。

### Chart

每种内置图表拥有一个 Definition，并可创建任意数量的 Component。Bootstrap 使用彼此狭窄的分层协作者组装 Definition：配置描述、数据需求描述、processor/projector、renderer、运行时设置描述和检查描述。Query、processing 与 presentation 只导入自身需要的协作者 contract，不导入完整 Definition。该目录项不是公开插件协议。

### Theme 与 Style

Theme 与 Style 是声明式展示能力。Theme 提供语义颜色角色与调色板，Style 描述兼容的视觉语法。两者都不读取 Provider 数据、不改变 Data Scope、不发起查询、不控制 TUI 生命周期，也不写入终端。

## 未来的 Animation 能力

Animation 是独立资源类型，不是 Chart 变体，也不是所有图表默认经过的后处理阶段。

未来的 Animation 资源可以：

- 通过 Standalone Host 运行；
- 占用 Dashboard Pane；
- 在不查询用量数据的情况下更新 Frame。

Chart Component 需要 Query 与 Result Processing；Animation Component 不需要。两者未来可能共享 Host、viewport、Frame、input 和 Painter 基础设施，但应等两类真实实现都存在后，再提取共同 Hosted Component 协议。

当前架构让 Route dispatch 与 Host/content composition 保持可扩展，但暂不添加无实现的 Animation route case 或资源 discriminator，也不定义 Animation Schema、插件协议、资源预算、帧节奏或 Dashboard Header 集成。Header 品牌、静态 Logo 与动画仍是彼此独立的未来设计问题。

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
