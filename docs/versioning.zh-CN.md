# 版本管理

`ccusage-viz` 在 `1.0` 前采用语义化版本管理：

- **补丁版本（`0.1.x`）**：修复问题、经过验证的渲染或查询改进、文档，以及 Alpha 阶段的 CLI 或交互调整。兼容性变化会在发行说明中注明。
- **次版本（`0.x.0`）**：`1.0` 前重大的新面向用户能力或数据源集成。
- 在 `1.0` 前，公开接口仍可能在各个版本之间变化。

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
