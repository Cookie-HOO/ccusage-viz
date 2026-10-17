# ccusage-viz

[English](README.md) · [使用指南](docs/usage.zh-CN.md) · [自定义命令协议](docs/custom-command-protocol.zh-CN.md) · [设计哲学](docs/design-philosophy.zh-CN.md) · [架构](docs/architecture.zh-CN.md) · [版本管理](docs/versioning.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![Python](https://img.shields.io/pypi/pyversions/ccusage-viz.svg)](https://pypi.org/project/ccusage-viz/) [![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE) [![CI](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml/badge.svg)](https://github.com/Cookie-HOO/ccusage-viz/actions/workflows/ci.yml)

> **Alpha · 0.3.0** — 在 1.0 前接口仍可能变化。当前方向请见[路线图](docs/roadmap.zh-CN.md)。

`ccusage-viz` 是面向 [`ccusage`](https://github.com/ryoppippi/ccusage) Token
数据的独立、非官方终端可视化工具。它把 `ccusage` 命令输出转换为交互式终端图表，
不会额外创建用量数据库。目前真实数据主要依赖 `ccusage`；本项目需要 `ccusage`，且**不内置**它。

## 快速开始

```bash
uv tool install ccusage-viz
ccuv dashboard
```

## 支持的 Agent

Agent 覆盖范围跟随 `ccusage`。其当前支持的 Agent 包括 Claude Code、Codex、OpenCode、Amp、
Droid、Codebuff、Hermes Agent、pi-agent、Goose、OpenClaw、Kilo、Kimi、Qwen、GitHub Copilot CLI、
Gemini CLI、Antigravity、Grok Build CLI 和 ZCode。完整且最新的列表，以及安装和各数据源的细节，
请参阅 [ccusage 支持列表](https://ccusage.com/)。

## 产品边界

ccusage-viz 可视化内置的 **Token 消耗** 与由其直接推导的指标，例如观测到的
每分钟 Token 数（TPM）。它不内置会话分析、调用次数、耗时指标、成本、定价、余额、
额度、配额或其他非 Token 的账户分析。注册的
[Dataset](docs/dataset-user-guide.zh-CN.md) 可以独立加入由外部数据源拥有语义的指标，例如阅读、CI、构建、金额、字节或本地服务活动，且不会改变 ccusage 的 Token 采集。

> 本项目与 `ccusage` 项目及其维护者没有隶属关系，也未获得其背书。

## Dataset 与自定义命令扩展

Dataset 让 ccuv 可视化由外部数据源拥有语义的指标，而无需把它们并入内置的 `ccusage` Token 采集。Dataset 是一个可执行命令：ccuv 向其 stdin 写入一份 JSON 请求，从 stdout 读取一份 JSON 响应，再把它声明的 Metric 渲染到聚焦图表或 Dashboard Pane 中。

### 安装官方 Dataset

官方 Dataset 收录在带签名的
[`Cookie-HOO/ccuv-dataset-catalog`](https://github.com/Cookie-HOO/ccuv-dataset-catalog)
仓库中。

1. 运行 `ccuv dataset`。
2. 按 `+`，选择 **Browse official datasets**。
3. 选择条目，检查 Metric、环境变量要求、版本和来源，然后确认安装。

官方目录会验证签名元数据；实际安装仍要求该 Dataset 为当前操作系统和架构发布了兼容 archive。

### 注册本地命令

使用命令的精确 argv，注册机器上已有的可执行程序：

```bash
ccuv dataset add-local /absolute/path/to/my-dataset --profile personal
ccuv dataset list
```

注册时会立即运行该命令的 Probe。后续 `--dataset` 应使用 Probe 返回的 Dataset ID，而不是可执行文件名。ccuv 保存 argv 并直接启动程序，不经过 shell。修改 Probe 元数据后可重新运行 `add-local`；相同 Dataset ID 的本地注册会被替换。

### 从指定 GitHub 仓库安装

也可以从指定 GitHub 仓库安装兼容 Dataset。以
[微信读书 Dataset](https://github.com/Cookie-HOO/ccuv-dataset-weread) 为例：

1. 运行 `ccuv dataset`，按 `+`，选择 **Install from GitHub**。
2. 输入：

   ```text
   https://github.com/Cookie-HOO/ccuv-dataset-weread
   ```

3. 检查发现的 Release，然后确认安装。

仓库必须发布兼容的原生 archive、checksum 和 Dataset manifest。从任意 GitHub 仓库安装并不代表它是官方 Dataset；如果该仓库同时存在于官方目录中，ccuv 会改用经过验证的官方 artifact 路径。

安装、管理、Dashboard 选择与排错请见 [Dataset 使用者指南](docs/dataset-user-guide.zh-CN.md)。实现并打包 Dataset 请从 [Dataset 开发者指南](docs/dataset-developer-guide.zh-CN.md)和[自定义命令协议](docs/custom-command-protocol.zh-CN.md)开始。

## 交互帮助

Dashboard 提供与当前界面对应的帮助：按 `h` 查看当前可用控制；在图表浏览模式中按 `c` 显示或隐藏控制栏。编辑 Overlay 文本或命令时，请使用 `Ctrl-H`，这样字面量 `h` 仍可输入草稿。

## Dashboard 预设

`dashboard` 将彼此独立配置的图表组合在同一终端中。未提供位置预设时，`dashboard` 默认使用 `wide-clock`：

> [!TIP]
> 若要在不创建默认 ccusage Pane 或请求的情况下启动，请使用 `ccuv dashboard --empty`。
> 它会以选定的默认网格或显式 `--grid`/layout 填充临时 `empty` Pane。可通过
> `--pane 'chart timeline --dataset reading --command "my-reader ccuv"'` 加入命令驱动的自定义数据。
> 安装、注册和使用 Dataset 请见 [Dataset 使用者指南](docs/dataset-user-guide.zh-CN.md)；
> 开发 Dataset 请见[自定义命令协议指南](docs/custom-command-protocol.zh-CN.md)。

```bash
ccuv dashboard
```

| 预设 | 命令 | 布局 | 预览 |
| --- | --- | --- | --- |
| `single` | `ccuv dashboard single` | 单个实时模拟时钟，无文字叠层和 Dashboard 边框。 | - |
| 【推荐-宽终端】 `wide-clock` **（未指定预设时的默认值）** | `ccuv dashboard wide-clock` | 推荐用于带紧凑实时数字时钟的通用总览。数字时钟 + 均衡 2×2。 | <img src="docs/assets/readme/dashboard-wide-clock.png" alt="预览" width="180"> |
| 【推荐-侧边栏】 `narrow-clock` | `ccuv dashboard narrow-clock` | 推荐用于带实时时钟的侧边栏。时钟 + 纵向 4×1。 | <img src="docs/assets/readme/dashboard-narrow-clock.png" alt="预览" width="180"> |
| `wide` | `ccuv dashboard wide` | 推荐用于只看数据的均衡总览。均衡 2×2。 | <img src="docs/assets/readme/dashboard-wide.png" alt="预览" width="180"> |
| `narrow` | `ccuv dashboard narrow` | 推荐用于窄终端中的紧凑总览。纵向聚焦。 | <img src="docs/assets/readme/dashboard-narrow.png" alt="预览" width="180"> |
| `all` | `ccuv dashboard all` | 推荐用于同时比较多种 Pane。宽广画廊。 | <img src="docs/assets/readme/dashboard-all.png" alt="预览" width="180"> |
| `spotlight-wide` | `ccuv dashboard spotlight-wide` | 推荐用于优先关注 Timeline 趋势。Timeline 主导。 | <img src="docs/assets/readme/dashboard-spotlight-wide.png" alt="预览" width="180"> |
| `spotlight-wide2` | `ccuv dashboard spotlight-wide2` | 推荐用于同时优先关注 Timeline 和 Stack。Timeline + Stack 主导。 | <img src="docs/assets/readme/dashboard-spotlight-wide2.png" alt="预览" width="180"> |

### 你的 Dashboard 预设

在 Dashboard 浏览模式中，按 `Ctrl-S` 可将当前 Dashboard 以名字保存，按 `Ctrl-P` 打开全屏预设管理器。管理器同时列出内置预设和你的预设；用方向键或 `j`/`k` 选择，按 `Enter` 加载，按 `s` 保存，按 `x` 删除选中的用户预设。内置预设可加载但不能删除。用与内置预设相同的名字保存用户预设会有意覆盖它；删除该用户预设即可重新显示内置预设。覆盖已有用户预设时，会要求选择覆盖或放弃。

预设名必须匹配 `^[a-z][a-z0-9-]*$`。保存后的预设可以在新终端中通过 `ccuv dashboard <name>` 启动。具名启动不接受配置覆盖；只能同时使用 `--demo`、`--lang`、`--empty` 和 `--ccusage-bin`。例如：

```bash
ccuv dashboard weekly-review
ccuv dashboard weekly-review --demo --lang zh-CN
ccuv dashboard weekly-review --empty
ccuv dashboard weekly-review --ccusage-bin /opt/bin/ccusage
```

具名预设的 `--empty` 会保留布局、权重、显示设置、刷新/采样节奏、时区、demo 和进程设置及其他安全的 ccuv 配置，但仅在内存中将每个 Pane 替换为空白 Pane；绝不会修改已保存的预设。原有未命名的 `ccuv dashboard --empty` 仍可用于临时组合新的 Dashboard。启用 demo 的预设加载后仍会启用 demo；Dashboard 目前没有运行时关闭 demo 的控制。

预设会持久化声明式 Dashboard 配置，包括已安装 Dataset 的引用、本地命令 argv 和可执行 Overlay 命令，但不会保存查询结果、环境变量、凭据或 UI/运行时状态。预设属于可信的用户本地自动化配置：加载预设会执行其中包含的命令，因此只能加载你信任的预设。预设保存在 ccuv 的私有状态目录 `dashboard-presets/presets.json`：macOS 为 `~/Library/Application Support/ccuv`，Windows 为 `%LOCALAPPDATA%/ccuv`，其他系统为 `${XDG_STATE_HOME:-~/.local/state}/ccuv`。缺少已安装 Dataset 不会使预设不可加载，受影响 Pane 会报告不可用的数据源；只有预设存储不可读、格式错误或版本不支持时才显示为不可用，并阻止覆盖写入。

> [!TIP]
> Dashboard 会协调 Pane 查询：多个 Pane 刷新时，相同的进行中 Provider 请求会被共享，避免重复工作。

## 聚焦图表视图

`ccuv chart KIND ...` 是聚焦单 Pane Dashboard 的快捷入口：它以指定图表启动，隐藏 Dashboard header 和全局 summary，之后完全使用 Dashboard 的 Pane 控制与生命周期。你可以保持单 Pane、替换 Pane，或扩展为多 Pane Dashboard。

| 分类 | 视图 | 命令 | 适用场景 | 预览 |
| --- | --- | --- | --- | --- |
| 时间趋势 `timeline` | 时间趋势 — 14 天 | `ccuv chart timeline` | 按模型、Agent 或项目分组查看近期每日 Token 趋势。 | <img src="docs/assets/readme/standalone-timeline-14d.png" alt="预览" width="180"> |
| 时间趋势 `timeline` | 时间趋势 — 13 个月 | `ccuv chart timeline --period 13mo` | 以更粗的时间尺度查看长期变化。 | <img src="docs/assets/readme/standalone-timeline-13mo.png" alt="预览" width="180"> |
| 活跃日历 `calendar` | 活跃日历 | `ccuv chart calendar` | 在较长范围内查看活跃日期、连续天数和用量集中的位置。 | <img src="docs/assets/readme/standalone-calendar.png" alt="预览" width="180"> |
| 分组构成 `stack` | 分组构成 — 构成 | `ccuv chart stack` | 查看输入、输出和缓存 Token 随时间的总体构成。 | <img src="docs/assets/readme/standalone-stack-composition.png" alt="预览" width="180"> |
| 分组构成 `stack` | 分组构成 — 缓存拆分 | `ccuv chart stack --cache split` | 比较缓存读取与缓存创建随时间的变化。 | <img src="docs/assets/readme/standalone-stack-cache-split.png" alt="预览" width="180"> |
| 累计排名 `ranking` | 累计排名 | `ccuv chart ranking --by project` | 找出指定范围内 Token 使用量最高的项目、模型或 Agent。 | <img src="docs/assets/readme/standalone-ranking.png" alt="预览" width="180"> |
| 终端动画 `animate` | 动画画廊 | `ccuv animate --gallery` | 无需 Provider 的纯呈现动画；可选指定初始样式，例如 `ccuv animate digital-clock --gallery`。`m` 打开本地样式和主题控制。 | <img src="docs/assets/readme/standalone-animation-gallery.gif" alt="预览" width="180"> |
| 监测 `monitor` | 趋势 | `ccuv chart monitor` | 通过重复累计快照观察进程内吞吐量，而非重建历史小时活动。采样基线建立后才开始观测；时间线样式会在可见时标记本次启动时刻。 | <img src="docs/assets/readme/standalone-monitor-throughput.png" alt="预览" width="180"> |
| 监测 `monitor` | 累计柱 | `ccuv chart monitor --style cumulative-bars` | 查看本地自然日内保留的 Token 增量。按 `w` 切换今天/昨天，按 `g` 切换每小时/半小时桶；未观测时段与已观测零值保持区分。 | <img src="docs/assets/readme/standalone-monitor-cumulative-bars.png" alt="预览" width="180"> |
| 监测 `monitor` | 排名 | `ccuv chart monitor --style ranking --by project` | 在观测窗口内按所选维度排名。 | <img src="docs/assets/readme/standalone-monitor-ranking.png" alt="预览" width="180"> |
| 监测 `monitor` | 列表 | `ccuv chart monitor --style list` | 在观测结果旁展示进程和条目详情。 | <img src="docs/assets/readme/standalone-monitor-list.png" alt="预览" width="180"> |
| 监测 `monitor` | 动画附件 | 在 `monitor` 的 `ranking` 或 `list` 样式中：按 `m`，再按 `s` | 数据下方的可选动画，默认关闭。`s`/`S` 循环适用效果和 ccuv 本地的 `无`；`t`/`T` 仅调整附件主题。它会等待可比较的已接受 interval，且绝不会触发额外用量查询。 | <img src="docs/assets/readme/standalone-monitor-animation.gif" alt="预览" width="180"> |

> [!TIP]
> 项目 Ranking 默认使用保守的 **Name** 聚合：无歧义的 Claude–Codex 配对会成为一个图表项目。按 `v`
> 打开数据视图，可看到聚合前的安全来源行；相同且非空的 `merge_group` 表示这些行会相加为同一个图表项目。
> 使用 `--project-aggregation exact` 可关闭跨 Agent 聚合。

> [!TIP]
> 想将多个聚焦图表一同查看？可以从聚焦图表会话添加 Pane，或直接组合自定义 Dashboard，并自行选择网格或命名布局。参阅[使用指南](docs/usage.zh-CN.md)。

已声明该能力的 V2 Dataset 可以在每个逻辑模型中独立排列真实模型：

```bash
ccuv chart ranking --dataset router --partition-by logical_model --group-by real_model
```

命令、筛选、控制、样式和数据语义请参阅[使用指南](docs/usage.zh-CN.md)。安装、注册和使用外部 Metric 请见[Dataset 使用者指南](docs/dataset-user-guide.zh-CN.md)；Dataset 作者请从[开发者指南](docs/dataset-developer-guide.zh-CN.md)开始。
[架构文档](docs/architecture.zh-CN.md)面向维护者。

## 安装、更新与卸载

需要 Python 3.11–3.13。`ccuv` 是 `ccusage-viz` 的短别名；两个已安装命令行为相同。

### 从 uv 安装

安装隔离的命令行工具：

```bash
uv tool install ccusage-viz
ccuv --version
```

更新或卸载：

```bash
uv tool upgrade ccusage-viz
uv tool uninstall ccusage-viz
```

### 从 pip 安装

在已激活的虚拟环境中安装或更新：

```bash
python -m pip install --upgrade ccusage-viz
ccuv --version
```

从该环境卸载：

```bash
python -m pip uninstall ccusage-viz
```

### 从源码安装

克隆仓库并安装可编辑工具：

```bash
git clone https://github.com/Cookie-HOO/ccusage-viz.git
cd ccusage-viz
uv sync --all-groups
uv tool install -e .
ccuv --help
```

拉取新版源码后，重新安装或卸载可编辑工具：

```bash
uv tool install --reinstall -e .
uv tool uninstall ccusage-viz
```

### 缺少 `ccusage`？

真实数据命令需要 `PATH` 中的 `ccusage`（或显式指定 `--ccusage-bin`）。在交互式终端中
缺少默认命令时，`ccuv` 会提供：

```bash
npm install -g ccusage
```

直接按空白的 **Enter** 或输入 `y`/`Y` 都会确认安装。输入其他文字、按 Ctrl-C 或发送 EOF
都会取消。Demo、重定向/非交互运行以及自定义 `--ccusage-bin` 运行不会提示或自动安装。
npm 不可用时，请手动安装 [`ccusage`](https://github.com/ryoppippi/ccusage)。

> [!TIP]
> 已发布的 `ccusage` 包不包含 DeepSeek Harness（DSH）统计。非官方的固定版本
> [`Cookie-HOO/ccusage-dsh`](https://github.com/Cookie-HOO/ccusage-dsh)
> 为 Windows、macOS 和 Linux 提供经过验证且支持 `ccusage dsh` 报告的原生构建。
>
> Windows x64（PowerShell）：
>
> ```powershell
> irm https://raw.githubusercontent.com/Cookie-HOO/ccusage-dsh/main/install.ps1 | iex
> ccuv dashboard --ccusage-bin "$env:LOCALAPPDATA\Programs\ccusage-dsh\ccusage-dsh.exe"
> ```
>
> macOS 或 Linux：
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/Cookie-HOO/ccusage-dsh/main/install.sh | sh
> ccuv dashboard --ccusage-bin "$HOME/.local/bin/ccusage-dsh"
> ```
>
> 安装脚本会验证 Release 校验和；也可以从
> [最新 Release](https://github.com/Cookie-HOO/ccusage-dsh/releases/latest)
> 手动下载 archive 和校验和。该项目仍是可能与上游产生偏差的非官方 fork；ccuv
> 本身没有 DSH collector。

## 延伸阅读

`ccusage-viz` 只关注 Token 且无状态：不会分析 Agent 对话内容，不会保存用量数据库，
也不会计算费用、额度、QPM 或速率限制指标。仅为 Codex 项目归因，它可能读取匹配本地 session 的
`session_meta.cwd`；不会保存或显示 session 日志内容。以下文档回答更深入的问题：

| 类型 | 文档 | 可以回答什么问题 |
| --- | --- | --- |
| 使用说明 | [使用指南](docs/usage.zh-CN.md) | 如何安装、配置、组合和调整图表与 Dashboard？ |
| 使用说明 | [Dataset 使用者指南](docs/dataset-user-guide.zh-CN.md) | 如何安装、管理、选择和使用本地、官方或 GitHub Dataset？ |
| 扩展开发 | [自定义命令协议](docs/custom-command-protocol.zh-CN.md) | 如何通过命令接入可相加的历史数据集、使用空白 Dashboard Pane，以及实现 JSON 契约？ |
| 扩展开发 | [Dataset 开发者指南](docs/dataset-developer-guide.zh-CN.md) | 如何开发、在本地测试、实现 Probe/查询、打包并发布 Dataset？ |
| 项目参考 | [设计哲学](docs/design-philosophy.zh-CN.md) | 哪些产品边界、配置归属和呈现原则是刻意的设计？ |
| 项目参考 | [架构](docs/architecture.zh-CN.md) | 为维护者说明 CLI 路由、Host、Pane、Provider、处理和渲染如何组织。 |
| 项目参考 | [路线图](docs/roadmap.zh-CN.md) | 计划、延后事项和反馈方向是什么？ |
| 项目参考 | [已知问题](docs/known-issues.zh-CN.md) | 已识别哪些间歇性 `ccusage` 问题，以及如何安全恢复？ |

可通过[Bug 报告表单](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=bug_report.yml)提交可复现问题，或通过[功能请求表单](https://github.com/Cookie-HOO/ccusage-viz/issues/new?template=feature_request.yml)提出改进建议。

本项目采用[GNU 通用公共许可证第 3 版（仅限 GPLv3）](LICENSE)。
