# 版本管理

`ccusage-viz` 在 `1.0` 前采用语义化版本管理：

- **补丁版本（`0.1.x`）**：修复问题、经过验证的渲染或查询改进、文档，以及 Alpha 阶段的 CLI 或交互调整。兼容性变化会在发行说明中注明。
- **次版本（`0.x.0`）**：`1.0` 前重大的新面向用户能力或数据源集成。
- 在 `1.0` 前，公开接口仍可能在各个版本之间变化。

## 0.3.5

`0.3.5` 将 Dashboard 预设与灵活拓扑明确分离，并改进升级体验；不改变 ccuv 默认依赖
官方 ccusage 的行为，也不改变内置 Token 语义：

- Dashboard 拓扑统一由 `--columns` 与前导 `--spotlight` Pane 数量表达：聚焦 Pane
  从上到下各占一整行，其余 Pane 按指定列数排列；全局 `z` 编辑器会事务式实时预览两个值，
  `{`/`}` 与 `J`/`K` 继续直接调整列宽和行高；
- `wide`、`narrow`、`all`、时钟变体与 `single` 继续作为完整预设；删除旧的
  `--grid`、`--layout`、`spotlight-wide` 与 `spotlight-wide2` 接口；
- 保存的 Dashboard 预设升级为 `ccuv.dashboard-presets/v2`；v1 不迁移、不加载，
  但首次保存新预设时会先归档原 v1 文件，再创建 v2 集合；损坏文件和未知 schema 仍禁止覆盖；
- README 现在优先介绍 ccusage Token 可视化，并把可选 DSH/WorkBuddy 覆盖与任意 Dataset
  指标统一放到后面的扩展数据来源章节；
- 官方 WeRead Dataset 更新不再提供其分组数据源无法处理的 Ranking 时间范围。

## 0.3.4

`0.3.4` 改进 Dataset 维护与自定义筛选编辑，不改变 ccuv 默认依赖官方 ccusage
的行为，也不改变内置 Token 语义：

- Dataset 刷新会检查受管理的官方/GitHub 安装是否存在新版，在列表和详情中展示
  当前版本与候选版本，并报告不可用和可升级数量；
- `u` 升级当前 Dataset，`U` 经确认后升级全部已检测候选；单项失败不会阻断其余升级；
- 自定义 Dataset 筛选会按尚未提交的 draft 更新各 Tab 数量，`C` 清空全部筛选，
  `1`/`2`/`3` 直接选择列数；
- README 增加可选 `my-ccusage` 原生安装说明，以及启用 DSH 与 WorkBuddy 时必须显式
  使用的 `--ccusage-bin my-ccusage` 参数。

## 0.3.3

`0.3.3` 修复 Windows Dashboard 交互，并让 Dataset 诊断更易检查，不改变查询或 Token Metric 语义：

- Windows 重定向文字输出改用 UTF-8，带 emoji 的时钟 Overlay 不再因 GBK 代码页失败；Windows VT 输入也会启用 Dashboard 鼠标报告，并在退出时恢复原控制台模式；
- Pane 调整支持双击聚焦、使用左右键或 Tab 循环选择前后 Pane，以及按拓扑使用上下键选择；文字和错误视图仍保留方向键滚动；
- 所有 Custom Dataset Pane 的 `L` 请求历史都支持与 Overlay 历史共用的选择交互，可复制单条安全协议请求及验证后的诊断，不包含凭据或原始 stderr；
- Dashboard 预设管理改用普通 `P`，避免终端保留的 Ctrl 组合键；控制栏、上下文帮助和公开文档保持一致。

## 0.3.2

`0.3.2` 改进 Windows 终端兼容性，并收紧 Dashboard、Dataset 与预设交互，不改变数据或 Token Metric 语义：

- Windows 控制台输入现在会规范化方向键等扩展按键，在可用时启用虚拟终端输出，并支持原生剪贴板复制；除 macOS `pbcopy` 外也支持 Linux Wayland/X11 剪贴板工具；
- 复杂 Unicode 动画行 fallback 会先绘制替换内容，再清除旧行尾；Windows 控制台即使无法隐藏同步输出的中间状态，带框 Dashboard Pane 也不会因整行先被清空而闪烁；
- Dataset 安装输入支持一致的编辑操作，能区分 GitHub 连接失败，并在 Dashboard 中按就绪状态显示全部注册项、缺失环境变量及对应帮助；
- Dashboard 预设管理使用 `P`，避免终端占用 Ctrl 组合键；列表与布局选择器支持方向键，具名预设允许时区覆盖；保存的预设保留语言、时区和 `ccusage-bin`，同时兼容已有预设文件；
- 语言检测现在依次参考显式覆盖、Windows/macOS UI 语言、标准 Locale 环境变量和 Python Locale fallback；包括繁体中文在内的中文 UI Locale 使用当前中文文案；
- Overlay 编辑将 Backspace 作为删除键、以 `?` 打开编辑帮助，并在动画 Pane 高级页使用 `h/j/k/l` 移动 Overlay，从而把方向键保留给 Pane 导航；
- Monitor 的 `ranking` 与 `list` 视图现在默认启用 `mole-cat` 附加动画，包括新插入的 Monitor Pane 以及所有使用这些视图的预设；时序 Monitor 视图仍默认不启用动画。

## 0.3.1

`0.3.1` 强化跨平台启动和小型 CLI 失败路径，并替换无法工作的 DSH 安装说明：

- 本地时区发现现在会优先使用 `tzlocal`，再进入已有的 Unix 导向 fallback；因此 Windows
  以及没有 `/etc/localtime` 的其他主机也能为日期边界和复制命令解析 IANA 时区；
- 省略必需的 `ccuv text` 预设时，现在会通过与无效预设相同的本地化错误路径列出支持的预设；
- README 不再建议通过 npm 的 Git 依赖流程安装 pnpm monorepo，而是链接到固定版本的非官方
  [`Cookie-HOO/ccusage-dsh`](https://github.com/Cookie-HOO/ccusage-dsh) 发行版；
  其校验和验证安装脚本为 Windows、macOS 和 Linux 提供启用 DSH 的原生构建。

DSH 发行版仍与 ccuv 相互独立：本版本不会增加 ccuv 原生 collector，也不改变内置 Token Metric 语义。

## 0.3.0

`0.3.0` 将 Dataset 扩展建设为一等数据源能力，并将聚焦图表统一到 Dashboard 运行时：

- Dataset 管理器可以注册本地命令、浏览带签名的官方目录，以及安装、更新或删除兼容的 GitHub Release artifact；
  已安装的数据源会在使用前执行 Probe，并始终是显式可执行命令，而不是进程内插件；
- 新增的 `ccuv.custom/v2` 协议支持多个带描述的 Metric、数据源拥有的标量值、历史图表与 Ranking、
  Custom Monitor observation、声明式周期、分组与分区维度、筛选、warning 和查询快照；同时继续支持遗留的
  V1 历史 Dataset；
- Dataset Pane 可以选择并事务式切换相关 Metric，保留有效的数据源自有刷新行为，并提供能力感知的控制和诊断，
  且不会在不同 Metric 之间混合 observation 或比较事实；
- Ranking 新增分组与分区结果、数据源描述与链接、标量值、本地搜索、复制操作、键盘与鼠标滚动、
  响应式虚拟化渲染，以及更明确的比较和 Top/Other 行为；
- `ccuv chart KIND` 现在把每个聚焦图表作为单 Pane Dashboard 启动，共享 Pane 生命周期、控制、检查视图、
  渲染与刷新行为；具名用户 Dashboard 预设可以持久化受信任的本地配置，并可在终端 UI 中管理；
- 终端帧差分、窄 Pane 布局、查询协调、项目 fallback 刷新、CLI 拼写错误指引、标题、帮助和双语 Dataset 文档
  均得到大量正确性与易用性改进。

兼容性说明：

- 聚焦图表命令现位于 `ccuv chart` 下，例如 `ccuv chart timeline` 和 `ccuv chart monitor`，不再使用此前的
  顶层图表路由；
- Dataset V2 是此 minor 版本引入的 Alpha 阶段协议，其数据源自有 Metric 语义与 ccuv 内置 Token 指标相互独立；
- Dashboard 预设中保存的 Dataset 命令和可执行 Overlay 命令属于受信任的本地自动化，加载配置时会运行。

本版本不增加 ccuv 原生用量 collector，也不改变内置 Token 指标的含义。

## 0.2.2

`0.2.2` 修复终端动画重绘行为并澄清 Dashboard 帮助，不改变 Token 收集或 Token 派生指标：

- 动画、画廊和 Dashboard 动画 Pane 使用更安全的原子终端重绘与光标清理，避免精确终端宽度帧的右侧频闪；
- Dashboard 帮助现将 Historical、Monitor 和页眉间隔拆开，说明生效默认值及仅可通过 CLI 配置的边界；
  同时将错过定时更新时的合并策略与查询限制分开，并统一说明 10 分钟无操作自动关闭；
- 在调整动画 Pane 时打开帮助不再引用废弃的本地化键。

此补丁版本不增加 collector、自定义命令、查询语义或 Token 指标能力。

## 0.2.1

`0.2.1` 改进动画 Host 与 Dashboard 的交互体验，同时保持 Token 收集与语义不变：

- 动画 catalog 与画廊集成现在跟随已安装的 `term-animate` catalog，其中包括新增的时钟动画；
- 动画 Overlay 增加仅在当前运行中存在的静态上下文或受信任本地命令输出。内置时钟预设默认在右下角
  使用反映本地时间的本地化状态命令；
- 默认 Dashboard 预设改为 `wide-clock`，其前导 `spotlight-wide` Pane 使用模拟时钟；
  `narrow-clock` 继续使用数字时钟；
- Dashboard 新增有界、仅会话内存在的撤销/重做和上下文帮助，并完善浏览、Pane 调整和 Dashboard
  调整模式中的按键与点击反馈；
- Dashboard 的退出处理尝试修复会话卡住后只能通过 `Ctrl-C` 退出的问题。该缓解措施仍在观测中，
  状态以已知问题条目为准。

这些仅是呈现与交互改进：Overlay/动画 deadline 不会新增 Token 查询，不引入 collector，也不改变
Token 派生指标的含义。

## 0.2.0

`0.2.0` 将终端动画作为一等呈现能力发布，同时保持 ccuv 的 Token 数据契约不变：

- `ccuv animate` 提供无需 Provider 的独立动画；ccuv 自己的 `--gallery` 可比较当前可用样式，
  不会委托给外部 CLI；
- Dashboard 支持显式动画 Pane，并新增 `wide-clock` 和 `narrow-clock` 预设；两者都拥有独立的
  时钟 Pane；
- Monitor `ranking` 和 `list` 增加可选动画附件。默认关闭；仅在出现可比较的已接受 interval 后显示，
  并只用已接受的 Token 增量为支持状态的效果判定活动；重绘 deadline 绝不会发起用量查询；
- 面向路径身份的项目归因与 `ccusage` Provider 处理更加保守、可靠，并补齐了对应的数据视图覆盖；
- 独立视图与 Dashboard 的终端交互和临时反馈行为得到改进。

动画只改变呈现：不会引入 collector、不会改变 Token 语义，也不会添加 ccuv 原生的 DSH 数据源。

## 0.1.3

`0.1.3` 改进 Alpha 阶段的交互与呈现契约：

- 历史范围、Monitor 查询范围、复制出的命令以及转发给 `ccusage` 的查询现在都以运行机器的本地自然日为准；
  `--timezone` 不再被接受。若此前依赖不同的 IANA 时区边界，请在该本地日期配置所对应的机器上运行 ccuv；
- 命令、完整命令、Markdown 表格和 JSON 检查页现在可以滚动完整的已渲染文本：使用 Up/Down、`h`（顶部）和
  `e`（末尾）。提示和控制栏保持固定，复制始终保留完整 payload；
- 已有的 Monitor `cumulative-bars` 呈现新增更清晰的日期/粒度标题、居中的本地时间标签、自适应柱宽、响应式图例、
  确定性的 Dashboard Demo 预热及 README 示例；
- 移除了当所有分组已经落在 `--top` 内、因而无需 Other 系列时的冗余提示。

本版本不会重建历史日内数据，也不包含任何 collector 集成。

## 0.1.2

`0.1.2` 为 Monitor 增加按本地时间段查看已保留 Token 增量的专用视图：

- `cumulative-bars` 将已接受的 Monitor 采样投影为本地日历日的 Token 柱，而非 TPM；
  沿用 Total、Agent、模型和项目分组，并在所选整天内确定 Top/Other；
- Monitor 调整新增今天/昨天以及每小时/30 分钟分桶。这些操作只重投影已保留采样，
  不会重新建立观测基线或改变采样频率；
- 分桶保留完整、部分和未观测覆盖状态；表格/JSON 输出会区分观测到的零值与缺失的观测，
  保留采样或重置造成的间隔，并处理本地夏令时回退日；
- Monitor 表格和 JSON 视图提供带时区的分桶边界、日期窗口、粒度、Token 单位数值、
  覆盖状态，以及已有的有边界项目显示 provenance 字段；
- 独立 Monitor 与 Dashboard Monitor 的控制、渲染、英文/简体中文使用指南和回归测试
  已围绕该视图对齐；
- Dashboard 的 `z` 布局选择器会保留固定容量布局的可见性，但会将无法容纳当前 Pane 数量的
  选项标为不可用，且导航会跳过这些选项。

这是仅限内存中已观测 Monitor 历史的功能；它不会从历史 provider 重建日内数据，
也不包含 collector 集成。

## 0.1.1

`0.1.1` 聚焦项目归属安全、交互可靠性和项目视图的可检查性：

- 更安全的项目呈现：绝不将 Claude 的不透明标识还原为文件系统路径；采用保守的 Claude–Codex Name 聚合、更清晰的带 Agent 的 Exact 标签，并改善不完整归属提示；
- 为按项目分组的 Monitor 提供 `--project-aggregation name|exact`，同时在显示投影前保留精确计数器和增量；
- 通过与图表一致的 `display_project` 标签及仅限当前 payload 的 `merge_group` 值，为项目 Markdown 和 JSON 数据视图提供有边界的聚合 provenance；Ranking 会把 Name 分组展开为安全的来源行，而 `Other` 保持仅聚合；
- Agent、模型和项目选择器改为完整值、不区分大小写的匹配；筛选、聚合、Monitor 计数器和显示统一使用小写模型 identity；
- 更清晰的候选查询、刷新和部分结果状态，包括历史视图、Monitor 和 TUI 中随终端宽度收缩的活跃筛选摘要；
- 针对已识别的 `unified_daily` 本地数据库瞬时失败提供恢复导向的处理：可能时保留已接受视图，UI 提供脱敏的重试/下次刷新提示，且不会暴露 stderr；
- standalone 和 Dashboard 调整模式在连续三分钟没有键盘或鼠标交互时自动返回；打开的筛选草稿会按与 `Esc` 相同的语义取消；
- 更新英文和简体中文的使用、设计、README 与已知问题指引。

`merge_group` 仅在当前数据 payload 内具有确定性，并非持久项目标识。其来源行是有边界的显示 provenance，不是原始记录或文件系统路径导出。

## 延后的 collector 集成

之后的次版本可在 npm 包形式的 `ccuv-collector` 及其 JSON 协议稳定后再集成。该集成将使用由 collector 所有、对 ccuv 透明的 agent identity 和 provenance 契约。
