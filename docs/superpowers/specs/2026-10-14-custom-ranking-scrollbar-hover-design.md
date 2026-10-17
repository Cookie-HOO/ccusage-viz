# Custom Ranking 滚动条悬停态设计

## 目标

优化 Custom Ranking（普通与分组）的右侧滚动条视觉层级：指针离开滚动条右侧 gutter 时显示紧凑轨道；指针进入 gutter 时恢复现有的完整滚动条外观。现有拖拽和轨道翻页交互保持不变。

## 交互与视觉

- 仅在结果溢出、滚动条存在时生效。
- 默认（指针不在任一有效 Custom Ranking 滚动条 gutter 内）：
  - 轨道占用现有的一列 gutter，不改变内容宽度或布局。
  - 所有轨道行以 muted 色细竖线绘制。
  - thumb 覆盖范围以 highlight 色绘制，表示当前可视窗口的长度与位置。
- 悬停（指针位于有效 scrollbar 的 gutter 单元内）：
  - 使用当前外观：thumb 为强调的实心字符，轨道为当前细竖线样式。
- 指针离开该 gutter 后，在下一次重绘立即恢复紧凑态。
- ASCII 模式延续对应的 ASCII 字符；颜色和是否加粗依旧由现有主题与颜色开关处理。

## 输入与状态

- 终端鼠标报告从按键/拖拽报告扩展为 all-motion 报告，以获得无按键的指针移动事件。
- Dashboard 保存当前悬停目标（可用 pane 标识或等价的布尔状态）。
- 每个鼠标移动事件使用已渲染的 pane 布局、frame 边界和 viewport 的 `Scrollbar.contains()` 判断指针是否位于有效 gutter。
- 悬停目标变化时触发正常重绘；不改变 viewport offset、焦点、选择或拖拽捕获。
- 释放、遮罩层/非 chart body、滚动条消失、布局变化时清除悬停状态。

## 渲染边界

- 将悬停状态作为渲染参数传入普通 Custom Ranking 和 grouped Custom Ranking viewport 渲染路径。
- 两个路径保留统一的 scrollbar 几何（`Scrollbar`）与命中测试；只按悬停状态改变轨道/滑块字符和强调样式。
- gutter 始终预留，因此切换状态不会造成表格换行、列宽变化或 viewport offset 抖动。

## 兼容性与异常处理

- 没有溢出、窗口过窄、当前 pane 不是 Custom Ranking、或 dashboard overlay 打开时，不显示或不维护悬停滚动条状态。
- 现有 wheel、thumb 拖拽与轨道点击仍依据相同 `Scrollbar` 实例运行；移动报告不能启动拖拽或触发翻页。
- 终端不提供鼠标移动报告时，保持紧凑默认态，同时现有点击和拖拽能力继续可用。

## 测试

- 为输入模式断言新增 all-motion 终端序列并确保退出时恢复。
- 为普通和 grouped viewport 断言：紧凑态轨道与高亮 thumb、悬停态现有完整样式、以及相同 scrollbar 几何。
- 为 Dashboard 断言：移动进入/离开有效 gutter 会切换状态；移动到其他 pane 或 overlay 下会清除；现有拖拽、轨道点击和 wheel 滚动不回归。
