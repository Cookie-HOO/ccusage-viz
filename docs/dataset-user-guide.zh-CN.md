# Dataset 使用者指南

[English](dataset-user-guide.md) · [开发者指南](dataset-developer-guide.zh-CN.md)

Dataset 用于接入 `ccusage` 之外的指标，例如阅读、CI、构建、花费或本地服务活动。ccuv 负责图表和交互，Dataset 可执行程序负责查询自己的数据源。

## Dataset 能做什么，不能做什么

Dataset 可以增加可独立选择的 Metric，并分别声明单位、filter、分组、summary、历史图支持和数据源拥有的 Monitor observation。Dataset 也可以把语义关联的 Metric 放进作者声明的 Metric Group，便于选择和快速切换。因此它适合接入阅读、构建、请求、金额、字节或本地服务活动等外部数据。ccuv 仍负责终端 UI、Dashboard 布局、刷新调度和内置 `ccusage` Token 图；Dataset 不会修改或并入内置 Token 采集。

目前每个 Dataset 都是 ccuv 在每次操作时启动的可执行命令：ccuv 向命令 stdin 写入一份 JSON 请求，从 stdout 读取一份 JSON 响应，然后命令退出。这不是插件系统、持久服务连接或文件导入功能。Dataset 内部可以访问自己的 API、文件、数据库或本地服务，但用户安装/注册的是可执行命令，而不是让 ccuv 直接连接 HTTP endpoint、socket、Python module 或数据文件。

## 开始前先看状态

交互管理器：`ccuv dataset`；只查看文字列表：`ccuv dataset list`。

只有 Dataset 已启用、最近 Probe 成功且所有必需环境变量存在时才是**可使用**。`需要配置` 表示缺少必需变量；`不可用` 表示最近刷新 Probe 失败；`已禁用` 表示不会出现在 Dashboard 选择器中，且不会被刷新。

## 安装或注册

### 本地命令

适合开发中的 Dataset 或机器上已有的工具。命令可有固定参数，ccuv 保存的是 argv，不是 shell 字符串：

```bash
ccuv dataset add-local /absolute/path/to/my-dataset --profile personal
ccuv dataset list
```

命令会立刻执行 Probe。后续 `--dataset` 使用的是 Probe 返回的 Dataset ID，而不是可执行文件名。开发者修改 Probe 后重新运行相同 `add-local` 即可刷新；相同 ID 会替换原本地注册。

也可在管理器中操作：`ccuv dataset` 后按 `+`，选 **Local command**，像在 shell 中一样输入命令，Enter Probe 并注册。这里只用 shell 式规则拆分文本为 argv，不会启动 shell。

### 官方 Dataset

1. 运行 `ccuv dataset`，按 `+`，选 **Browse official datasets**。
2. 用 `j/k` 或方向键选 Dataset，Enter 查看版本、支持图、环境变量和来源详情。
3. 再按 Enter 下载、校验、安装、注册当前平台的 release asset；Escape 返回不安装。

官方目录有签名校验，但某项仍可能因没有当前 OS/arch 的 archive 而不可安装。

### 任意兼容 GitHub 仓库

1. `ccuv dataset`，按 `+`，选 **Install from GitHub**。
2. 输入 `OWNER/REPOSITORY` 或 `https://github.com/OWNER/REPOSITORY`，Enter。
3. ccuv 查找 latest release、当前平台 archive 和 checksum，并展示确认界面。
4. Enter 安装；Escape 编辑或取消。

仓库必须发布兼容的 native archive、checksum 和有效 manifest；缺任一项都会拒绝安装。GitHub 安装不等于官方 Dataset；若该仓库也在官方目录，ccuv 会走官方验证 artifact。

## 管理器完整操作

| 操作 | 按键 | 会发生什么 |
| --- | --- | --- |
| 选择 | `j` / `k` 或方向键 | 移动当前注册项。 |
| 详情 | Enter | 查看 Metric、支持图、环境变量、来源、版本；Enter/Esc 返回。 |
| 添加 | `+` | 选择官方、GitHub 或本地命令。 |
| 刷新 | `r` | 对每一个启用的 Dataset 重跑 Probe，更新安全元数据。Dashboard 在选择器中选中 Dataset 后、进入 Metric/chart kind 选择前也会重新 Probe。 |
| 启用/禁用 | `d` | 切换当前项能否用于 Dashboard 和刷新。 |
| 删除 | `x` | 确认后删除。本地只删除 ccuv 注册；官方/GitHub 还删除受管理安装文件。 |
| 升级 | `u` | 有可用更新时确认并安装新 Release。 |
| 帮助 | `h` | 查看当前管理器控制和配置说明。 |
| 退出 | Ctrl-C | 关闭管理器。 |

必需变量要在启动 ccuv 的环境中设置，例如：

```bash
export EXAMPLE_ACTIVITY_TOKEN='...'
ccuv dataset
```

管理器只展示变量名和 Dataset 提供的设置说明，绝不会显示或保存值。改完环境变量后重启 ccuv 并按 `r`。

## 在 standalone 中使用

先选 Metric 声明过的图类型。`--dataset` 是注册 ID；多 Metric Dataset 没有 default Metric 时必须给 `--metric`，想选择非默认 Metric 时也要给。

```bash
ccuv chart timeline --dataset example-activity --metric events
ccuv chart ranking --dataset example-activity --metric events --period 30d
ccuv chart monitor --dataset router --metric tokens
```

通过 `ccuv dataset` 的详情查看每个 Metric 支持哪些图。历史 Metric 可以支持 Timeline、Calendar、Stack、Ranking 的任意组合；只有声明 Monitor capability 的 Metric 才能运行 Monitor。

当 Dataset 声明 Metric Group 时，交互式 Dataset 选择器会显示本地化的 Group 标题，并把成员 Metric 缩进到标题下；空 Group 不显示。未加入 Group 的 Metric 仍在所有 Group 后平铺显示。未声明 Group 的 Dataset 保持原有平铺选择器。窄选择器中向上导航会先显示被裁掉的组标题，再让选择回绕，以保留当前 Metric 的上下文。

在已选中的 Custom 图 Pane 内，`m` 和 `M` 会在当前 Group 中支持当前图表类型的 Metric 间前后循环。ccuv 会保留当前查询选择；如果下一个 Metric 的声明 capability 不接受当前 period、group 或 granularity，则保持当前 Metric 并显示短暂警告。成功切换后替换已选 Metric；目标请求失败时保持此前的图或 Monitor 选中。

Dataset 可建议初始 period、group、Top N、Other、style、theme 和 Monitor 本地显示范围，但只是建议。显式参数优先：

```bash
ccuv chart timeline --dataset example-activity --metric events \
  --period 30d --group-by project --top 3 --filter category=work \
  --style points --theme classic
```

Custom Dataset 使用 `--group-by`，不是内置图的 `--by`；只有 Dataset 已返回对应运行时 option 时才可使用可重复的 `--filter ID=OPTION`。带 `--dataset` 时不能同时用内置 `--agent`、`--model`、`--project`、`--cache`。无效 Dataset default 只会忽略对应字段，不会阻止图表打开。

## 在 Dashboard 中使用

### 交互方式

1. 用 `ccuv dashboard --empty` 启动干净布局，或打开普通 Dashboard。
2. 聚焦 Empty Pane，按 `r`（或双击）选择类型。
3. 选择 **Dataset**，选一个可使用的注册项；多 Metric 时选 Metric。声明了 Metric Group 时，Metric 会缩进显示在对应 Group 标题下。
4. 从该 Metric 支持的 chart kinds 中选一种。
5. ccuv 重新 Probe、应用有效首屏建议、再查询 Pane。配置或源端错误会显示在 Pane，不会用零覆盖数据。

之后可在 Pane 调整 period、group、Dataset 本次响应提供的 filter、Top、Other、style、theme、Monitor 本地显示范围。这些是当前运行本地状态，不会修改 Dataset 或注册。

### CLI 声明 Pane

```bash
ccuv dashboard --empty --grid 2x2 \
  --pane 'chart timeline --dataset example-activity --metric events' \
  --pane 'chart ranking --dataset example-activity --metric events --period 30d' \
  --pane 'empty' \
  --pane 'chart monitor --dataset router --metric tokens'
```

每个 `--pane` 都是正常 chart fragment。Metric capability 仍限制 ccuv 实际会发送的请求；CLI 参数仍会覆盖 Dataset default。Preset 会保留 Custom Ranking 的条目间距和 Monitor 附件；共享同一 Dataset ID 的 Pane 必须解析为相同命令，ccuv 会拒绝含混的来源命令，而不是静默选择其一。

## 保存、迁移与排错

Dashboard preset 会保存 Dataset ID、图表配置、本地命令 Dataset 的 argv 和命令驱动 Overlay，但不会保存查询结果、环境变量或凭据。因此 preset 属于可信的本地自动化配置：加载它会执行其中保存的命令，只能保存和加载你信任的 preset。若需要在其他机器复用，建议发布 GitHub 或官方 Dataset。

| 现象 | 检查方法 |
| --- | --- |
| `Dataset ... is not installed` | `ccuv dataset` 添加/注册，并使用 Probe 返回的 ID。 |
| `需要配置` | 详情中查看必需变量，设置后重启 ccuv 并按 `r`。 |
| GitHub 无法安装 | repo 需要 latest 非 draft release、平台 `.tar.gz`、checksum 和有效 manifest。 |
| Metric 或图类型不能选择 | Probe 没声明 capability；换支持的 Metric/kind 或联系开发者。 |
| filter/group 失败 | capability 可能变了；按 `r` 刷新后选择声明过的值。 |
| Monitor 时间范围似乎不对 | Dataset 的 `window_seconds` 是事实窗口；本地 `window` 控制仅改变 ccuv 显示多少已接受历史。 |
| 请求失败后仍显示旧图 | 同一查询刷新失败会保留最后接受的图；变化后的查询只显示候选/错误，不混用旧选择的数据。 |
| Dashboard 选择 Dataset 后显示“不可用” | 新 Probe 发现没有可选 Metric/chart capability，或 Dataset 响应无效。用 `ccuv dataset` 检查 Dataset，修复配置后重试。 |
| Dashboard 拒绝 Dataset 命令冲突 | 同一 Dataset ID 的 Pane 必须使用等价 argv（指向同一文件的绝对路径别名可接受）。替换或移除冲突 Pane。 |
