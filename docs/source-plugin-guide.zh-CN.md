# Source 插件开发指南

> **状态：**未来 Source 插件的数据契约。插件系统尚未实现；本文用于约束后续协议设计。

Source 插件把一个外部 Token 数据来源转换为 ccuv 可以合并和绘图的标准记录。插件只提供数据，不负责图表、TPM、筛选、分组或终端渲染。

## 准入要求

Source 必须：

1. 提供按自然日统计的累计 Token 消耗；
2. 当天累计值随实际调用持续更新；同一日期与维度组合的新记录表示该组合当前的完整累计值，而不是再次追加的增量；
3. 为每条记录提供 `agent`、`model` 和 `project` 三个维度；
4. 提供标准 Token 数值和明确的日期 Coverage；
5. 声明数据实际统计自哪些产品、文件、服务或 API。

不能满足这些要求的数据来源不应作为 Source 插件接入。

## 维度与名称

| 维度 | 有具体值时 | 无法细分时 |
| --- | --- | --- |
| `agent` | 提供真实且稳定的 Agent 名称；希望与 ccusage 数据合并时，应采用相同名称 | 为全部记录提供一个稳定的统一名称 |
| `model` | 提供真实且稳定的 Model 名称 | 为全部记录提供一个稳定的统一名称 |
| `project` | 提供真实且稳定的 Project 名称 | 为全部记录提供一个稳定的统一名称 |

一条累计事实的完整标识是 `Source ID + 自然日 + agent + model + project`。同一 Source 后续返回相同标识时，新累计值替换旧累计值，不能把两次快照相加。不同 Source 的当前事实分别保留；ccuv 在最终统计中相加已启用且由使用者确认不重叠的 Source。任一维度名称不同都会分开。ccuv 不推断别名、不做模糊匹配，也不修正插件提供的名称。

例如：

```text
ccusage: agent = claude
plugin:  agent = claude
结果:    合并为 claude
```

```text
ccusage: agent = claude
plugin:  agent = claudecode
结果:    claude 与 claudecode 分开
```

如果插件无法区分 Model，可以让所有记录使用一个稳定名称，例如 `my-source-model`。如果开发者不希望不同来源被合并，应使用能够明确区分来源的稳定名称。

维度名称的选择、稳定性以及名称合并造成的语义后果由插件开发者负责。

## 数据来源与重复计数

ccuv 会合并启用的数据来源，但不会推断两条记录是否描述了同一次 Token 使用，也不会执行事件级去重。

Source 插件不得统计 ccusage 官方认可的数据来源；这些来源由内置 ccusage Provider 负责。否则，同一 Token 使用可能被重复累计。

插件必须清楚声明统计来源，例如：

```text
Data sources:
- Example Router local event database
- Records produced after 2026-01-01
- Does not read Claude Code or Codex logs handled by ccusage
```

插件开发者负责准确披露来源和已知重叠风险。使用者负责确认同时启用的多个 Source 不会重复覆盖相同数据；由来源重叠造成的重复计数由使用者承担。

## 职责边界

Source 插件负责：

- 读取自己的数据来源；
- 输出每日、当天可更新的 Token 记录；
- 提供三个标准维度；
- 维护维度名称；
- 声明数据来源和已知重叠范围。

ccuv 负责：

- 合并已启用 Source 的标准记录；
- 根据用户配置执行筛选、分组、Top 和 Other；
- 从当天更新的样本计算 Monitor 增量与 TPM；
- 生成 Chart Model 并完成终端渲染。

ccuv 不负责：

- 猜测两个维度名称是否等价；
- 修正 Source 的命名；
- 判断不同 Source 是否重复统计了同一事件；
- 为重叠数据执行自动去重。
