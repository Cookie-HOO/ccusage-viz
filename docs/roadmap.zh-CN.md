# 路线图

[English](roadmap.md)

`ccusage-viz` 当前版本为 **0.2.2**。本路线图描述公开产品契约和已排序的需求池，不是私有实现计划。

## 0.2.x

- `0.2.x` 将终端动画建设为一等呈现能力：无 Provider 的 standalone 动画、ccuv 自有的 gallery 浏览、明确的 Dashboard 动画 Pane、时钟预设，以及可选的状态感知 Monitor 附件。动画只影响呈现，不改变 Token 或 Dataset 数据语义。
- 持续完善 Dashboard 布局、Pane 调度和全局摘要，不增加兼容性别名。
- 评估面向长范围 Watch 和 Dashboard 历史 Pane 的、识别 interval 的已完成结果缓存，以及有界的最近/历史刷新。当前轮询在正确性、失效语义和数据源特定语义验证完成前保持不变。

## 0.3.x

- `0.3.x` 以 Custom Dataset 为公开数据源能力的核心：在保持 Dataset 自己拥有数据源语义的前提下，发展 Dataset 发现、安装、开发者契约、Metric 选择和 Dashboard 交互。
- 仅在协议、生命周期、资源和兼容性契约明确后，继续发展 Metric Group、分组 Metric 选择、图内切换和 Monitor 行为等相关 Custom Dataset 能力。
- 此发布序列为无法在 `0.2.x` 兼容引入的 Custom Dataset 契约变更预留空间。

## 需求池

- **可恢复的 Custom Monitor Metric 切换：** 用户切离已访问的关联 Metric 后，在明确资源上限内保持其采样流运行；切回时恢复已保留的 observation 和 baseline，如同从未被隐藏。此能力需要为按 Metric 生命周期、调度、取消、保留上限、错误隔离进行独立设计，并保证 observation 与比较事实绝不跨 Metric 混合。

## 反馈

- [Bug 报告](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
- [功能请求](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)
