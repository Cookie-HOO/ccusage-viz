# 路线图

[English](roadmap.md)

`ccusage-viz` 当前版本为 **0.3.5**。本路线图描述公开产品契约和已排序的需求池，不是私有实现计划。

## 已在 0.2.x 交付

- 终端动画成为一等呈现能力，包括无 Provider 的 standalone 动画、ccuv 自有的 gallery 浏览、明确的 Dashboard 动画 Pane、时钟预设，以及可选的状态感知 Monitor 附件。动画只影响呈现，不改变 Token 或 Dataset 数据语义。

## 当前 0.3.x 发布线

- `0.3.0` 将 Custom Dataset 建设为一等公开数据源能力，包括 Dataset 发现与安装、开发者契约、Dashboard 交互、V2 Metric Group、分组选择、Pane 内关联 Metric 切换、数据源拥有的值和 Custom Monitor 支持。
- 在保持 Dataset 自己拥有数据源语义的前提下，继续强化 Dataset 生命周期与交互。进一步的保留行为只在协议、资源和兼容性契约明确后交付。
- 持续完善 Dashboard 布局、Pane 调度、终端性能和全局摘要，不增加兼容性别名。
- 评估面向长范围 Dashboard 历史 Pane 的、识别 interval 的已完成结果缓存，以及有界的最近/历史刷新。当前轮询在正确性、失效语义和数据源特定语义验证完成前保持不变。

## 需求池

- **可恢复的 Custom Monitor Metric 切换：** 用户切离已访问的关联 Metric 后，在明确资源上限内保持其采样流运行；切回时恢复已保留的 observation 和 baseline，如同从未被隐藏。此能力需要为按 Metric 生命周期、调度、取消、保留上限、错误隔离进行独立设计，并保证 observation 与比较事实绝不跨 Metric 混合。

## 反馈

- [Bug 报告](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)
- [功能请求](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)
