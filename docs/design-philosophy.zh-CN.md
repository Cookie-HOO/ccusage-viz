# 设计哲学

本文记录 `ccusage-viz` 稳定的产品概念与设计约束。命令语法、默认值、完整快捷键和 Preset 参数属于用户文档；实现与版本安排属于设计规格和 Roadmap。

## 产品边界与形态

1. **产品只表达 Token 消耗及受支持的直接衍生指标。**

   只有数据源能够直接且可靠表达的 Token 指标才进入产品。目前唯一的速率指标是 TPM。费用、金额估算、调用或请求次数、配额、QPM、速率限制，以及从 Token 数量推测出的其他指标均不在产品范围内。

2. **Standalone 和 Dashboard 是两种产品形态。**

   每个交互式图表界面都是 TUI。Standalone 独立运行 Timeline、Calendar、Stack、Ranking 或 Monitor；Dashboard 在一个 TUI 中组织多张独立配置的图表。

3. **Pane 保留对应 Standalone 的数据与图表语义。**

   Pane 是 Standalone 内容在 Dashboard 上下文中的超集，只增加焦点、位置、顺序和切换等组合能力。Dashboard 行为不得改变底层图表的时间或指标契约。

   **例外：**Pane 的刷新与采样节奏由 Dashboard 统一拥有；复制为 Standalone 命令时再物化对应 Interval。

## 配置所有权

1. **Dashboard 设置只控制其明确拥有的范围。**

   配置所有权分为三类；设置只影响所属类别，不通过隐式继承改写另一类别。

   | Dashboard 独立设置 | 作用范围 | Pane 行为 |
   | --- | --- | --- |
   | Layout、Weights、焦点、Pane 顺序 | Dashboard 几何与导航 | 不构成 Pane 配置 |
   | 全局暂停、Controls | Dashboard 会话外壳 | Pane 不拥有局部暂停或 Controls 状态 |
   | Dashboard Theme、Style | 外壳、Header 与 Summary | 不改变 Pane Theme 或图表 Style |
   | Header Style、Summary 周期 | Dashboard Header | 不改变 Pane Density、Scope 或 Granularity |

   | Dashboard 全局唯一设置 | 对 Pane 的影响 |
   | --- | --- |
   | ASCII | 外壳和所有 Pane 统一使用基础字符并禁用颜色 |
   | 真实或 Demo 数据源模式 | Summary 和所有 Pane 使用同一种数据源模式 |
   | Demo Size | Demo Summary 和所有 Pane 使用同一量级 |
   | Timezone | Summary 和所有 Pane 使用相同的自然日边界与时间标签 |
   | Refresh Interval | 驱动 Summary 和所有历史 Pane；Pane 不拥有 Watch 或局部刷新 |
   | Sampling Interval | 驱动所有 Monitor Pane；Pane 不拥有局部采样周期 |

   | Pane 独立设置 | 所有权边界 |
   | --- | --- |
   | 时间范围、Filters | 每个 Pane 独立定义 Data Scope |
   | By、Top、Other | 每个 Pane 独立定义分析与可见系列 |
   | Theme、Style、Density、Legend | 每个 Pane 独立定义图表呈现；Theme 不继承 Dashboard Theme |
   | 图表专属设置 | 只属于对应 Pane |

   Pane 配置和 Pane 片段不得包含 Demo Mode 或 Demo Size。Standalone 仍独立拥有自己的 Demo 设置、Timezone、Interval、刷新和暂停行为。每个 Pane 都必须可以独立解释；复制为 Standalone 时再物化 Dashboard 拥有的必要上下文。

2. **进程上下文不是 Pane 配置。**

   Language、`ccusage` 可执行文件、查询超时和 Provider 执行环境在进程内统一生效，但不构成 Pane 的可覆盖设置。

## 数据范围与分析语义

1. **时间与 Filters 共同定义 Data Scope。**

   时间范围、时区，以及 Agent、Model、Project Filters 决定图表和 Summary 使用的数据集合。同一维度内按 OR 组合，不同维度之间按 AND 组合。各维度候选仅由时间范围和时区决定，不相互收窄。

2. **By、Top 和 Other 不改变 Data Scope。**

   By 将范围内的数据组织为可见系列；Top 裁剪这些系列；Other 决定是否合并被裁剪的系列。Summary 始终聚合完整 Scope。Other 不占 Top 名额且始终位于最后。Ranking 隐藏 Other 时在标题中显示 `Top N · 占总量 X%`；显示 Other 后恢复完整 Scope 覆盖并省略占比。

3. **展示范围与比较 Coverage 相互独立。**

   展示范围决定图表中的日期，比较 Coverage 只为 Summary 提供基线。Component 拥有已接受的比较事实、Coverage 与补充状态。持续 Host 会把适用但未覆盖的比较渲染为 `??`，并且只查询缺失区间：相邻缺口可以合并，彼此分离的基线保持独立，不扩张成一个连续范围。成功但为空的已覆盖区间是数值零；补充请求失败时保留 `??` 并添加局部 Notice。

4. **滚动与固定日期模式保持不同承诺。**

   Period 定义随所选 Timezone 中自然日推进的滚动范围。Day 表示包含今天的尾随窗口；Month、Quarter、Year 包含指定数量的自然日历周期，并从最早周期边界持续到今天。因此，`14d` 表示今天及此前 13 天，`1mo`、`1q`、`1y` 分别表示本月至今、本季度至今和本年至今。不需要自然周期对齐的尾随跨度始终可以换算成 Day 表达。

   提供 Since 或 Until 即进入固定日期模式；单独 Until 非法，单独 Since 在启动时根据所选 Timezone 将结束日期解析为当天。所有固定日期视图都明确展示解析后的起止日期，单独 Since 也不使用特殊的 Since-to-date 标题。固定边界在会话中不再推进：若范围包含启动当日，当日累计值仍可变化；跨过所选 Timezone 的午夜后，范围继续停留在原日期并成为完整历史范围。Granularity 独立于日期模式，默认 Day，并可在不改变范围的情况下调整。

5. **历史 Ranking 与 Monitor Ranking 只共享视觉语法。**

   历史 Ranking 对日期范围内累计的 Token 消耗排序。Monitor Ranking 只对最新有效累计采样对排序：Total 与 Model 使用单调时钟实际经过时间计算 TPM，Agent 与 Project 使用该采样对的 Token 增量。保留的 Timeline 历史不会重新定义或回填当前 Ranking 值。两者不共享时间或指标契约。

## 数据一致性与异步结果

1. **`??` 只表示所需数据尚未取得。**

   `??` 是统一的加载中占位，表示当前有效状态所需的数据未知且已经进入刷新流程，包括防抖等待、待执行或执行中。已提交的修改使对应数值失效时，应立即显示 `??`；不得继续展示旧配置或其他配置的结果，造成它仍与新状态一致的假象。只有受影响的数值变为未知；纯展示修改和能够从已接受数据重新计算的数值继续可用。不得用 `??` 表达真实零值、无数据、错误、不可用或不适用；这些状态必须各自明确呈现。只有已覆盖区间内缺失的记录才可以解释为真实零值。

2. **每次数据相关调整都会创建新 generation。**

   候选配置和可见结构立即更新；需要补充的数据可以异步到达。连续调整最终必须收敛到一个内在一致的状态。

3. **只有最新 generation 可以改变当前画面。**

   过时结果可以进入适用的缓存或 Coverage，但不得覆盖最新候选状态。各组件独立拥有 generation、Coverage、Observer、成功时间和错误状态。

4. **持续 TUI 允许最终补齐。**

   Watch、Monitor 和 Dashboard 可以暂时显示 `??`，并在后续结果到达时补齐。Historical no-Watch 完成所需查询并渲染一次已接受结果后退出，不依赖未来的周期 Tick。

## 展示与视觉语义

1. **Density 控制狭义图表之外的信息量。**

   Density 只有三种取值。Minimal 保留身份、图表和紧凑运行状态；Compact 增加当前筛选 Scope 的 Token 值与有效 Filter 维度数，不显示比较或审计；Full 增加适用的周期比较和 Host 提供的运行审计。Standalone 默认 Full，新建或默认 Pane 使用 Compact。Dashboard 不存在全局图表 Density。

2. **Theme、Style 与 Density 各自承担单一职责。**

   Theme 控制语义颜色；Style 控制当前对象的视觉语法；Density 控制信息量。Dashboard Style 专门控制边框、分隔、间距和焦点强调，不传播到 Pane 图表 Style。

3. **Summary 跨产品形态共享指标与比较语法。**

   Standalone 与 Pane Summary 在 By、Top、Other 投影之前，根据图表自身筛选 Scope 一致计算和呈现 Token 数值及比较。独立的 Dashboard Header Summary 拥有未筛选数据与 Coverage，不继承 Pane Scope。身份、Summary 和运行状态保持为彼此独立的信息。固定日期范围不推断范围外的比较基线。

4. **Controls 和 Notices 独立于 Density。**

   Controls 是会话级交互外壳，可以隐藏以归还空间。影响正确理解的重要 Notice 不得仅因 Density 较低而消失。在 Dashboard 中，每条 Notice 都保留在其来源 Pane 内的有界区域；Notice 不做全局聚合或去重，一个 Pane 也不能占用另一个 Pane 的空间。

5. **动态 TUI 是首要体验，同时为其他环境提供明确退路。**

   默认产品体验是持续运行且可在运行时调整的 TUI。Historical 也支持 no-Watch 的一次性使用方式，ASCII 则为老旧或能力受限的终端提供显式兼容路径。能力检查应明确失败并建议受支持的运行方式，不得静默改写用户配置。具体参数、冲突、终端要求和降级行为属于第三层配置与终端参考文档。

## 交互原则

1. **CLI 提供初始状态，TUI 提供所见即所得的高频调整。**

   用户可以通过 CLI 给定初始配置，也可以使用默认命令进入 TUI 后再可视化调整。运行时入口只覆盖会话中可能反复比较或改变的产品设置；调整必须立即反映当前有效状态，并可通过复制命令复现。

   **例外：**会话中通常不会改变、需要开放字符串输入、改变整个数据生命周期，或属于执行环境的设置只在 CLI 中提供，不出现在运行时调整中，包括 Timezone、ASCII、真实或 Demo 数据源模式、Language、`ccusage` 可执行文件、查询超时和 Provider 执行环境。Dashboard 的 Timezone、ASCII 和数据源模式仍统一作用于 Summary 和所有 Pane，Pane 不可覆盖。运行时界面可以通过实际渲染、Full Details 或 Full Command 体现这些有效值，但不提供只读设置项。Demo Size 是数据源模式内部的显示量级，在 Demo 模式中仍可运行时调整。

2. **运行时可调整配置使用显式模式，例外执行意图使用 Flag。**

   对于可持久化、可复制，并由用户在运行时比较或调整的设置，即使当前只有两个状态，CLI 也使用带值参数明确表达模式。CLI、TUI、状态展示与复制命令共享同一组概念和规范值，使命令无需依赖默认值，也无需在 TUI 状态与正向或否定 Flag 之间转换。例如，Weekdays 与 Other 使用 `show | hide`，Stack Cache 使用 `combined | split`。Compact Command 可以省略默认模式；Full Command 必须显式列出全部有效模式。

   **例外：**通常不出现、参数本身即可完整表达意图，且不属于普通运行时可调整设置的醒目能力选择或执行生命周期例外，可以保留为 Flag。当前例外是 ASCII 和 Historical no-Watch。模式统一不得为已经由 Density、Style 或 Layout 等上层设置完整控制的行为制造冗余开关。

3. **能力通过 Quick 和 Advanced 渐进呈现。**

   Quick 与 Advanced 按使用频率划分，而不是按数据与外观的内部分类划分。Quick 覆盖常见分析流程中的 Data Scope、分析方式与主要呈现；Advanced 放置低频、精细或条件性控制。两者操作同一份即时配置，当前上下文无意义的选项应省略，而不是禁用后继续展示。

   Standalone 与 Dashboard 全局调整统一只使用两行：第一行展示运行状态与当前生效设置，第二行展示当前 Quick 或 Advanced 操作。Dashboard Pane 调整先使用相同的两行图表区域，再以分隔线隔开两行 Dashboard 管理操作，分别负责内容/生命周期与位置/焦点。`a` 只切换图表操作行；Dashboard 管理操作在任一页面都可用。普通调整中 Enter 与 Escape 都保留已生效修改并退出。不提供可点击的“完成”。窄终端按完整操作单元隐藏低优先级项，并用 `…(+N)` 精确提示仍可通过键盘使用的操作数量；页面身份、`a` 切换与 Enter/Escape 提示始终保留。

4. **有限档位保留并如实显示合法启动值。**

   CLI 可以接受比 TUI 常用档位更广的合法值。TUI 必须保留并显示当前具体值，不标记其来源，也不得因打开设置、浏览或返回而自动吸附。当前值在常用序列中时从当前位置继续；不在序列中时，第一次明确调整进入序列首项，之后只在常用档位间循环。复制命令始终反映当前有效值。Standalone、Dashboard 和 Pane 中的同类设置遵循相同规则。

   **例外：**Layout Weights 直接基于当前整数比例调整，不从预设序列首项重新开始。没有运行时入口的自由文本或执行参数也不受此规则约束。

5. **除非有效取值必须依赖草稿，否则配置即时生效。**

   大部分设置在每次调整时立即提交；可见配置立即更新，能够从已接受事实推导的数据也立即重新计算。因此，普通设置界面中的 Enter 与 Escape 含义相同：都保留当前有效状态并离开界面。两者都不保存、放弃或回滚已经生效的修改。Layout 和 Weights 遵循同一规则。

   **例外：**只有完成输入或选择后才能形成有效取值的操作使用隔离草稿，包括 Filter、Layout、Pane Replace 与 Pane Add。Enter 提交完整且合法的草稿；Escape 只放弃当前子操作并返回父级调整。Layout Editor 显示当前 `auto` 或 `行x列` 输入，非法输入会保留并显示错误。Pane Replace 在原列表索引原子安装全新默认 Pane，并终止被替换 Pane 的生命周期。Pane Add 使用 `N` 在焦点 Pane 列表索引之前插入，使用 `n` 在其后插入。固定布局保留列数；插入或添加需要更多容量时扩展行数，删除后不自动缩减。只有操作具有破坏性、难以恢复或后果不够清晰时才增加二次确认，普通可逆配置不需要确认。

6. **已提交配置与展示数据必须描述同一状态。**

   数据相关修改一经提交，应立即更新可见配置、使旧工作失效，并为新状态建立立即刷新意图。尚未取得的新状态数值显示 `??`。短暂的尾沿防抖可以把连续修改产生的中间刷新合并为针对最新状态的一次请求，但不得延迟配置展示、数据失效、占位符或 generation 更新。离开即时设置界面时，无论按 Enter 还是 Escape，都应立即触发仍在防抖等待中的最新刷新意图。

   只有受影响的数值变为未知：纯展示修改只重绘；能够从已接受数据完整计算的修改立即重新处理；需要新数据的修改显示 `??`，直到当前 generation 被接受。过时 completion 不得恢复旧值或清除占位符。Pause 只抑制周期 backlog，不阻止已提交配置或手动刷新产生的显式补齐；该补齐完成后也不会恢复周期调度。

7. **按键表达稳定概念，而不是通用大小写规则。**

   `m` 始终表示修改当前图表：在 Standalone 中修改当前视图，在 Dashboard 浏览模式中修改当前 Pane；点击 Pane 会选择它并执行等价操作。大写 `G` 打开 Dashboard 全局设置，点击 Header 是等价入口。大写字母通常不反向循环对应小写选项。相关按键也可以分别代表同一概念下稳定且不同的类别：`p` 循环常用尾随周期，`P` 循环常用自然周期至今。界面必须标明当前类别，避免把自然周期误解为尾随时长。

   **例外：**Theme 有较多且会增长的候选，保留 `t` 向前和 `T` 向后切换。`N` 与 `n` 是有意设计的语义对，分别在当前 Pane 列表索引之前或之后插入。其他普通字母操作只接受小写。

8. **方向操作同时支持方向键与 `hjkl`。**

   任何提供上、下、左、右导航或调整的上下文，都必须分别接受 `k`、`j`、`h`、`l`，并执行完全相同的状态变化。界面提示可以根据空间合并表达两组按键，但不能让两种入口产生不同边界、循环或确认行为。

9. **职责边界防止语义混乱，而不是禁止有价值的多入口。**

   Standalone、Dashboard 和 Pane 共享术语、顺序、状态表达与调整行为，但一个操作只出现在目标明确的上下文中。多个入口可以表达同一意图，但必须产生相同结果。一个交互概念不得暗中改变另一个概念，例如调整 Granularity 不会改变 Period。

10. **阻止启动的配置错误提供统一且可执行的诊断。**

   启动配置应在进入 TUI 前原子校验。诊断必须定位到具体命令层级、Pane、参数或取值，解释违反的约束，并在能够可靠判断意图时给出最小语义改动的完整建议命令及修改摘要。修复优先保留意图：可信的近似拼写替换、移动到正确所有权范围、修正结构关联或夹取数值边界，最后才删除无意义参数。无法可靠确定意图时应提供少量明确候选，而不是伪造唯一答案。运行时数据、Provider、终端空间或无数据状态不属于命令修复。

11. **检查视图先展示内容，再允许复制。**

   Chart 模式不显示复制能力。Command、Markdown Table 和 JSON 等非 Chart 视图应明确标记当前内容和下一视图，复制操作必须复制当前完整内容。

   **例外：**Dashboard 全局只提供紧凑命令和完整命令，不提供跨 Pane 的 Markdown 或 JSON。每个 Pane 独立拥有自己的 `v` 视图循环：Chart、Command、Full Command、数据表和数据 JSON。Dashboard 不提供临时终端文本选择 `c` 模式；普通 xterm 鼠标上报持续用于 Pane 选择，并在终端清理时恢复。

## Dashboard 布局与尺寸

1. **Layout 决定拓扑，Weights 只描述当前拓扑内的相对尺寸。**

   Auto 在稳定软性舒适目标下选择一列或两列；Grid 每行最多两列且奇数末项跨行；Focus 让首个 Pane 占据重点行；Stack 每行一个 Pane。切换 Layout 会为新拓扑重建等权 Weights，不保留其他 Layout 的隐藏比例，也不从终端像素反推。命令只记录当前 Layout 适用且经最大公约数规范化的正整数 Weights，不记录终端绝对尺寸。

2. **Pane 共享列比例与各行高度。**

   调整列比例影响共享列，调整行高度影响对应行。Pane 重排只交换内容，不改变几何。固定网格插入或添加 Pane 时保留现有列数，只追加容纳所需的行数；删除不会隐式缩减该拓扑。不支持任意坐标、重叠、每格独立拓扑、分页或 Pane 滚动。

3. **Safety Minimum 只保障正确性，不强制舒适可读。**

   Dashboard 使用很小且统一的安全下限，防止无效几何并保留身份、焦点与紧凑诊断。显式 Layout 和 Weights 不因低于建议视觉尺寸而被阻止；稀疏 Ranking 和 Monitor Ranking 可以在较小空间中继续工作。

4. **Renderer 在自己的 Pane 内适应和降级。**

   Renderer 根据空间减少标签、刻度、装饰或可见行。只有无法产生有意义输出时才显示局部空间提示；单个 Renderer 的需求不得触发全局重排。

5. **Auto 只使用稳定的软性目标。**

   Auto 可以考虑 Pane 数量和可用空间，但不得根据当前数据改变布局。可读性最终由用户通过 Weights、Density、Top、Legend 和 Style 控制。

## Dashboard 调度、执行与重绘

1. **Dashboard 使用两条固定 Tick 序列。**

   Refresh Tick 同时向 Summary 和历史 Pane 提供机会；Sampling Tick 同时向 Monitor Pane 提供机会。两条基线在会话中保持固定，不因执行耗时、成功或失败、手动刷新、暂停或继续而移动；修改一个 Interval 只重建对应序列。

2. **数据相关调整在防抖后补齐最新状态。**

   设置立即生效并创建新 generation；现有数据足以计算的内容立即更新，缺失部分显示 `??`。只有最新状态仍缺少必要数据时，才在短暂尾沿防抖后提供一次刷新机会。连续调整重置防抖，因此不会为每个中间状态发起查询。固定 Tick、手动刷新或继续若先发生，则满足并取消尚未触发的防抖机会，且不移动 Tick 基线。

   **例外：**纯展示调整和能够完全由现有数据计算的调整不安排查询；Interval 变化只重建对应 Tick 序列。

3. **共同触发不意味着共同完成。**

   每个组件独立开始、完成、失败、校验 generation 并接受结果。慢 Pane 不延迟其他 Pane，Tick 也不是完成屏障。

4. **慢组件最多保留一个 Pending。**

   组件运行中遇到下一 Tick 时不启动重叠工作，只记录一次 Pending；完成后立即处理。多个错过的 Tick 不排队。过短 Interval 可能使查询持续运行，这是可观察的配置结果，不应被系统静默修正。

5. **Execution Coordinator 减少物理工作，但不合并业务状态。**

   Summary 和 Pane 产生带 owner、generation、trigger、logical plan、数据源模式与执行选项的逻辑请求。Coordinator 对严格等价的 in-flight 物理查询去重，并可共享产品明确证明安全的 Monitor 原始快照，再把不可变结果独立交付给各 owner。

   **例外：**Coordinator 当前不合并不同日期范围或 Filters，不构造 Provider 字段超集，不复用已完成的过时结果，也不延迟 Tick 收集批次。Provider 专属实现只有显式提供合并与拆分契约时，才能执行更高级优化；Interval 语义始终位于 Coordinator 之外。

6. **自动更新提交完整逻辑 Frame。**

   每次结果都形成完整 Frame，再与上一 Frame 比较并只写变化的终端行。组件可以按各自结果到达顺序独立更新，不能通过局部物理写入绕过 Frame 状态。

7. **刷新包含结果所需的重新计算与重绘。**

   `r` 始终刷新当前上下文；由刷新数据产生的排序、派生计算和完整重绘都是同一次操作的结果，不提供独立的重排或重绘命令。Dashboard 手动刷新向所有组件提供立即刷新机会，使绘制缓存失效并覆盖完整 Dashboard；继续执行同样的刷新与重绘后恢复固定 Tick。Resize 自动重算全部几何并清除旧区域，但不要求查询数据。完整重绘不等于无条件清屏。

   **例外：**Pause 只停止周期 Tick；暂停期间不产生周期工作或积累 backlog，但手动刷新和用户修改配置后经防抖合并的一次性补齐仍可执行。此类补齐不会恢复周期调度。Monitor 建立基线、出现采样间隙、暂停/恢复、修改影响数据的配置或检测到计数器重置时，会清空独立的当前观测，直到形成下一组有效采样对；已保留的 Timeline 历史继续可用，不连续处仍显示为 Gap。Standalone Watch 与 Monitor 保留自己的刷新、暂停和 Interval 行为。

## 可复现性与文档边界

1. **有效配置必须可以通过命令复现。**

   复制 Dashboard 时展开实际 Layout、Weights、Panes 和全局设置；复制 Pane 时生成可执行的 Standalone 命令并物化 Dashboard Timezone 与适用的 Interval。紧凑命令省略默认值，完整命令显式列出有效配置。

2. **Preset 是完整启动模板，不是运行时模式。**

   Preset 提供完整的 Dashboard 基础状态，并可在启动命令中接受显式覆盖或追加 Pane；没有 Preset 时，除无参数 `dashboard` 外，必须显式提供 Pane。任一运行时可序列化配置被编辑后，来源标记永久消失；启动时的组合以及刷新、暂停、Controls 可见性、检查视图、查询结果和 Resize 等会话行为不影响标记。复制命令始终展开实际状态，而不是保留 Preset 名称。

3. **会话状态不进入可复现配置。**

   当前焦点、暂停状态、Controls 可见性、检查视图和临时错误属于运行会话，不应写入复制的命令。

4. **设计哲学只记录稳定约束。**

   完整 CLI 拼写、参数矩阵、快捷键表、Preset 内容和操作示例属于用户指南；组件接口、状态机和测试标准属于正式设计规格。新增功能应能归入本文原则；必须破例时，应明确写出例外及边界。

5. **文档按认知深度分层，并在同一次维护中保持一致。**

   README 通过自然语言和小型产品地图建立第一印象；架构文档定义已经实现的所有权与运行边界，设计哲学解释稳定原则与理由。正式设计规格保留决策和测试标准，Roadmap 只描述计划工作。英文与简体中文文档必须表达相同契约；术语、默认值或所有权发生变化时，应同步协调这些层级，而不是延后处理。
