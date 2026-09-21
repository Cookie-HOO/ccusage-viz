# 版本管理

`ccusage-viz` 在 `1.0` 前采用语义化版本管理：

- **补丁版本（`0.1.x`）**：修复问题、经过验证的渲染或查询改进、文档，以及不改变现有公开工作流的其他改动。
- **次版本（`0.x.0`）**：新的面向用户能力、数据源集成，或可能需要迁移的公开契约变更。
- 在 `1.0` 前，公开接口仍可能在次版本之间变化。

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

DSH 专属 provider 与 contract 试验不属于 `0.1.1`。

`0.1.1` 发布当前已完成的工作。之后的次版本可在 npm 包形式的 `ccuv-collector` 及其 JSON 协议稳定后再集成。该集成将使用由 collector 所有、对 ccuv 透明的 agent identity 和 provenance 契约，而不是 DSH 专属 ccuv provider。
