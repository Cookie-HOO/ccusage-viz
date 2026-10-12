# Custom 指标解释展示设计

## 目标

复用 `ccuv.custom/v2` 已有的 `metrics[].description` 双语字段，让用户能够在选择 Custom Dataset 指标时理解指标含义，并在选中 Custom Pane 后通过 `h` 帮助再次查看当前指标解释。

指标选择界面改用与 Dashboard 帮助一致的分组、缩进、强调与弱化文案层级，减少现有平铺列表的空白感。

## 范围

- 不修改 Custom 协议，不增加 `help`、`explanation` 或其他新字段。
- 仅使用 V2 Metric 的既有 `title` 与 `description`。
- 更新中英文协议文档，明确 description 的宿主展示用途。
- 选择器和 Pane 帮助使用当前应用语言选择本地化文本。

不改变 V1 Dataset、非 Custom Pane、指标切换语义、数据请求或持久化格式。

## 指标选择器

Dataset 选定后，Metric 选择器保留现有的 Dataset 标题和选择提示，但以树状层级渲染内容：

1. 声明的非空 `metric_groups` 依既有声明顺序显示为一级分组标题，采用帮助面板的分组强调样式。
2. 各 Group 成员依 `metrics[]` 声明顺序显示为二级可选指标。使用树枝前缀（`├─` / `└─` 或与现有帮助渲染等价的终端字符）及缩进；当前选择仍使用现有 `›` 和选中高亮。
3. 每项指标紧随一个三级说明行（或按宽度换行的说明行），展示 `description`，相对标题弱化，并继续缩进至该指标之下。
4. 未分组指标仍排在所有 Group 后，保持既有顺序；它们同样以“指标 → 说明”的两级结构呈现，但不人为生成 Group 标题。
5. 分组标题和说明行不可选择；方向键和 `j`/`k` 只在实际指标项间移动，Enter 仍解析到原 `metrics[]` 索引。

布局应沿用现有 chooser 的安全截断、宽度与重绘约束。说明过长时按可用宽度换行，不遮挡选择标记，也不改变可选项的逻辑索引。

## Pane 帮助

选中已经取得可用 V2 descriptor 的 Custom Pane 后，按 `h` 打开既有 Dashboard 帮助弹窗。帮助中增加“当前指标”分组：

- 显示当前 Metric 的 title；
- 在其下以帮助面板的弱化、缩进文本显示 description，并按面板宽度换行；
- 该分组位于与当前 Pane 相关的帮助内容中，遵循既有帮助树状视觉语言。

V1 Custom Pane、非 Custom Pane，以及尚未拥有可用 descriptor 或无法解析当前 Metric 的 Custom Pane 不显示该分组。帮助不得使用旧响应或候选切换目标的元数据，避免指标解释与当前已接受 Pane 不一致。

## 数据流与边界

协议解析和 `V2MetricDescriptor` 已保存 `description`，本次只将其传到选择器和帮助渲染边界。Metric chooser 继续通过稳定的原始 metric index 完成选择；展示行可增加分组/说明等非选择行，但不得改变配置写入的 `metric_id`。

帮助从当前 Pane 已接受的 descriptor 及其当前已提交 `metric_id` 查询 Metric。Metric 切换的候选请求未成功前，帮助仍对应原已接受 Metric；切换成功提交后，下一次帮助对应新 Metric。

## 错误处理

协议层现有本地化 description 校验保持权威。渲染层不为缺失或不可用的 descriptor 补造说明；直接省略“当前指标”组。选择器只能使用已验证的 Probe descriptor，因此每个 V2 Metric 都有可安全显示的双语 description。

## 验证

- 单元测试覆盖平铺 Dataset 与含 Groups Dataset 的 chooser 行：Group、Metric、description 的显示顺序与原始 metric index 映射正确。
- 键盘导航跳过 Group 与 description 行；Enter 仍选择预期 metric。
- 窄宽度下 description 正确换行/截断，选中高亮与树状前缀不损坏。
- 中文和英文分别显示对应 title/description。
- Custom V2 Pane 的 `h` 帮助显示已接受当前 Metric 的 title 和 description。
- V1、非 Custom、未接受 descriptor 的 Pane 帮助不显示当前指标组。
- Pending Metric 切换不提前替换帮助文本；成功提交后更新。
- 现有选 Metric、分组、帮助、V1 和 Dashboard 行为无回归。

## 文档

更新 `docs/custom-command-protocol.md` 与 `docs/custom-command-protocol.zh-CN.md` 的 V2 Metric 说明，声明现有 `description` 是 Metric 的本地化解释，宿主可在 Metric 选择与当前 Pane 帮助中展示它；不将其解释为请求字段或业务数据。
