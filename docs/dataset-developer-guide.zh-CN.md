# Dataset 开发者指南

[English](dataset-developer-guide.md) · [协议参考](custom-command-protocol.zh-CN.md) · [使用者指南](dataset-user-guide.zh-CN.md)

本文从零开始说明如何开发可执行的 `ccuv.custom/v2` Dataset。完成后你会拥有一个可本地注册的命令、能理解 Probe/各类查询、能在 standalone 和 Dashboard 中测试，并知道如何发布 GitHub Release。

## Dataset 能做什么

Dataset 可以把 `ccusage` 不拥有的数据源接入 ccuv。它可声明一个或多个可独立选择的 Metric、单位、双语标签、源端维度和 filter，以及每个 Metric 支持的图类型。根据 capability，Dataset 可以提供：

- Timeline、Calendar、Stack、Ranking 所需的可加历史事实；
- 当 ccuv 不应聚合时，由数据源拥有的不可加历史值；
- 数据源拥有的固定窗口 Monitor observation，例如每分钟事件数；
- 当前值/比较摘要，或明确不提供摘要；
- period、group、filter、Top/Other、style、theme、Monitor 本地显示范围的兼容首屏建议。

它不会成为 ccuv 的 collector，也不会改变内置 Token 计算。ccuv 负责终端渲染、交互、允许时的本地 Top/Other 投影、调度和 Dashboard 布局；Dataset 负责访问数据源、定义源端语义和聚合，并返回 protocol 响应。

## 先理解边界

Dataset 是**无状态可执行适配器**，不是 Python 插件，也不是常驻服务。ccuv 每次查询都会：启动你配置的 argv（不经 shell）、向 stdin 写入一份 UTF-8 JSON 后关闭 stdin、从 stdout 读取一份 UTF-8 JSON、等待进程退出。

因此：stdout 只能写协议响应 JSON；日志与调试信息写 stderr；不要依赖上一次进程调用留下的内存状态。新 Dataset 应使用 V2：一个 Dataset 可声明多个 Metric，每个 Metric 可支持历史图、Monitor 或两者。

这也是当前**唯一**受支持的 Dataset 集成形式。Dataset 必须是本地可执行命令，或从经过验证的 Dataset archive 安装出的可执行命令。ccuv 不加载 Python module、共享库或插件；不支持 HTTP、WebSocket、gRPC、持续 stdin 会话；不监控 Dataset 专用文件格式；也不从文件、socket 或 callback 获取 Dataset 响应。你的命令内部可以调用 API、读取数据库/文件、访问本地服务，但它和 ccuv 的边界始终是：每个进程执行中，一份 stdin JSON 请求对应一份 stdout JSON 响应。

## 最小可运行 Go 实现

推荐用 Go 开发需要发布的 Dataset。纯 Go 程序能编译成一个独立可执行文件，用户不必安装 Go、Python 或虚拟环境；而且很容易为 ccuv 支持的平台分别交叉编译。

创建 Go module，将下列程序保存为 `cmd/example-activity/main.go`。它是完整的 V2 stdin/stdout 骨架；固定返回值仅用于先验证协议，之后替换 `handleChart` 和 Monitor 分支中的数据源读取逻辑。

```go
package main

import (
  "encoding/json"
  "fmt"
  "os"
  "time"
)

const protocol = "ccuv.custom/v2"
const datasetID = "example-activity"
type Request struct { Protocol string `json:"protocol"`; RequestID string `json:"request_id"`; RequestKind string `json:"request_kind"`; MetricID string `json:"metric_id"`; Range map[string]any `json:"range"` }
func text(en, zh string) map[string]string { return map[string]string{"en":en,"zh-CN":zh} }
func unit() map[string]any { return map[string]any{"id":"event","label":text("events","事件"),"placement":"suffix","decimal_places":0} }
func ok(r Request, p map[string]any) map[string]any { out:=map[string]any{"protocol":protocol,"request_id":r.RequestID,"request_kind":r.RequestKind,"dataset_id":datasetID,"status":"ok"}; for k,v:=range p { out[k]=v }; return out }
func descriptor() map[string]any {
  project:=map[string]any{"id":"project","label":text("Project","项目")}
  hist:=map[string]any{"granularities":[]string{"day"},"group_by":[]any{nil,"project"},"periods":[]string{"7d","14d","30d"}}
  return map[string]any{"revision":"example-activity-1","version":"0.1.0","default_metric_id":"events","dataset":map[string]any{"title":text("Example activity","示例活动"),"description":text("Minimal V2 Dataset","最小 V2 Dataset")},"metrics":[]any{map[string]any{"id":"events","title":text("Events","事件"),"description":text("Daily activity","每日活动"),"unit":unit(),"aggregation":"sum","summary":"total","capabilities":map[string]any{"group_by":[]any{project},"charts":map[string]any{"timeline":hist,"ranking":hist,"monitor":map[string]any{"window_seconds":60,"refresh_interval_seconds":10,"group_by":[]string{"project"}}}},"defaults":map[string]any{"timeline":map[string]any{"period":"14d","group_by":"project","top":5,"style":"line-points","theme":"nord"},"monitor":map[string]any{"style":"ranking","window":"6h"}}}},"environment":[]any{}}
}
func handleChart(r Request) map[string]any {
  start,_:=time.Parse("2006-01-02",r.Range["start_date"].(string)); end,_:=time.Parse("2006-01-02",r.Range["end_date"].(string)); points:=[]any{}
  for day:=start; !day.After(end); day=day.AddDate(0,0,1) { points=append(points,map[string]string{"date":day.Format("2006-01-02"),"value":fmt.Sprintf("%d",1+day.Day()%5)}) }
  return ok(r,map[string]any{"metric_id":"events","descriptor":descriptor(),"runtime":map[string]any{"filters":[]any{}},"data":map[string]any{"series":[]any{map[string]any{"id":"example","label":text("Example","示例"),"points":points}}}})
}
func main() {
  var r Request
  if err:=json.NewDecoder(os.Stdin).Decode(&r); err!=nil || r.Protocol!=protocol { os.Exit(1) }
  var response map[string]any
  switch r.RequestKind {
  case "probe": response=ok(r,map[string]any{"descriptor":descriptor()})
  case "chart": response=handleChart(r)
  case "monitor": response=ok(r,map[string]any{"metric_id":"events","observation":map[string]any{"end_at":r.Range["end_at"],"total":"42","groups":[]any{}}})
  case "summary": response=ok(r,map[string]any{"metric_id":"events","summary":map[string]any{"metric":map[string]any{"id":"events","label":text("Events","事件"),"current":map[string]any{"value":"42","display":text("42 events","42 个事件")},"sequential":map[string]string{"status":"unavailable"},"year_over_year":map[string]string{"status":"unavailable"}}}})
  default: response=map[string]any{"protocol":protocol,"request_id":r.RequestID,"request_kind":r.RequestKind,"dataset_id":datasetID,"status":"error","error":map[string]any{"code":"invalid_request","message":text("Invalid request","无效请求")}}
  }
  json.NewEncoder(os.Stdout).Encode(response)
}
```

构建、直接 Probe、注册单一二进制：

```bash
go mod init example.com/example-activity
go build -o bin/example-activity ./cmd/example-activity
printf '%s\n' '{"protocol":"ccuv.custom/v2","request_id":"dev-probe","request_kind":"probe"}' | ./bin/example-activity
ccuv dataset add-local "$PWD/bin/example-activity"
ccuv dataset list
ccuv chart timeline --dataset example-activity --metric events
ccuv chart monitor --dataset example-activity --metric events
```

上面的 stdin 管道是最快的调试路径：必须只输出一份 JSON 并以 0 退出。修改 Probe 描述后再次运行 `add-local` 会刷新同 ID 的本地注册。

### Python 等动态语言：仅作本地参考

Python 完全可以用于本地开发或私有部署，但公开分发时不应假定用户拥有相同 Python 版本、venv 路径和依赖。动态语言项目可显式注册 runtime，例如：

```python
#!/usr/bin/env python3
import json, sys
from datetime import date, datetime, timedelta

PROTOCOL = "ccuv.custom/v2"
DATASET_ID = "example-activity"

def text(en, zh): return {"en": en, "zh-CN": zh}
def unit(): return {"id":"event","label":text("events","事件"),"placement":"suffix","decimal_places":0}
def ok(req, **payload):
    return {"protocol":PROTOCOL,"request_id":req["request_id"],"request_kind":req["request_kind"],"dataset_id":DATASET_ID,"status":"ok",**payload}

def descriptor():
    return {
      "revision":"example-activity-1", "version":"0.1.0", "default_metric_id":"events",
      "dataset":{"title":text("Example activity","示例活动"),"description":text("Minimal V2 Dataset","最小 V2 Dataset")},
      "metrics":[{
        "id":"events", "title":text("Events","事件"), "description":text("Daily activity","每日活动"),
        "unit":unit(), "aggregation":"sum", "summary":"total",
        "capabilities":{
          "group_by":[{"id":"project","label":text("Project","项目")}],
          "charts":{
            "timeline":{"granularities":["day"],"group_by":[None,"project"],"periods":["7d","14d","30d"]},
            "ranking":{"granularities":["day"],"group_by":["project"]},
            "monitor":{"window_seconds":60,"refresh_interval_seconds":10,"group_by":["project"]}
          }
        },
        "defaults":{"timeline":{"period":"14d","group_by":"project","top":5,"style":"line-points","theme":"nord"},"monitor":{"style":"ranking","window":"6h"}}
      }], "environment":[]
    }

def daily_facts(start, end):
    rows=[]
    while start <= end:
        rows.append({"date":start.isoformat(),"value":str(1 + start.day % 5)})
        start += timedelta(days=1)
    return rows

def error(req, code, field, value):
    return {"protocol":PROTOCOL,"request_id":req["request_id"],"request_kind":req["request_kind"],"dataset_id":DATASET_ID,"status":"error","error":{"code":code,"message":text("Unsupported query","不支持的查询"),"unsupported":{"field":field,"value":value}}}

def main():
    req=json.load(sys.stdin)
    if req.get("protocol") != PROTOCOL: raise SystemExit("unsupported protocol")
    kind=req.get("request_kind")
    if kind == "probe": response=ok(req, descriptor=descriptor())
    elif kind == "chart":
        r=req["range"]; start=date.fromisoformat(r["start_date"]); end=date.fromisoformat(r["end_date"])
        response=ok(req, metric_id="events", descriptor=descriptor(), runtime={"filters": []}, data={"series":[{"id":"example","label":text("Example","示例"),"points":daily_facts(start,end)}]})
    elif kind == "monitor":
        end_at=datetime.fromisoformat(req["range"]["end_at"])
        response=ok(req, metric_id="events", descriptor=descriptor(), runtime={"filters": []}, observation={"end_at":end_at.isoformat(),"total":"42","groups":[{"id":"example","label":text("Example","示例"),"value":"42"}]})
    elif kind == "summary":
        response=ok(req, metric_id="events", summary={"metric":{"id":"events","label":text("Events","事件"),"current":{"value":"42","display":text("42 events","42 个事件")},"sequential":{"status":"unavailable"},"year_over_year":{"status":"unavailable"}}})
    else: response=error(req,"invalid_request","request_kind",str(kind))
    json.dump(response,sys.stdout,separators=(",",":")); sys.stdout.write("\n")
if __name__ == "__main__": main()
```

```bash
ccuv dataset add-local /absolute/path/to/.venv/bin/python /absolute/path/to/dataset.py
```

## Probe：必须声明什么

Probe 只能返回元数据：不能获取收费业务数据、校验 secret、改变源端状态。ccuv 在注册、Dataset 选择、以及 Custom Monitor 启动前使用它。

| 字段 | 你应声明什么 | ccuv 如何使用 |
| --- | --- | --- |
| `revision`、`version` | 数据集元数据版本 | 展示并保存安全的 Probe 快照。 |
| `dataset` | Dataset 名称和描述 | Dataset 管理器、选择器中的文案。 |
| `metric_groups` | 可选的有序 Group；具有稳定 ID 和双语标题 | 在选择器中组织关联 Metric，并定义 `m/M` 快速切换边界。 |
| `metrics` | 彼此独立的度量；每项可通过 `group_id` 引用一个 Group | 让用户选 Metric，并限制可选图表。 |
| `unit` | 稳定 ID、双语标签、前/后缀、精度 | 格式化图、表格和 summary 数值。 |
| `aggregation` | `sum` 或 `value` | 决定 ccuv 是否能做本地历史投影、Top/Other。 |
| `capabilities` | 维度与支持图类型 | 生成静态控制，并限制 ccuv 发出的请求。若历史 Ranking 的源端原始行数有固定上限，也可声明 `max_items`。 |
| `runtime.filters` | 当前查询上下文的 filter 维度、option，以及 `multi_select` / `single_select` 模式 | 仅随每次成功 chart/Monitor 响应返回；为该 accepted snapshot 启用 `f` filter 编辑器。 |
| `defaults` | 可选首屏建议 | 仅应用兼容字段；错误字段会忽略。 |
| `summary` | `comparisons`、`total`、`none` | 决定是否发 summary 请求。 |
| `environment` | 所需变量名、获取方法 | 显示配置状态，绝不保存变量值。 |

所有人类文本必须同时有 `en` 和 `zh-CN`。所有度量值都必须是十进制**字符串**，如 `"42"`、`"1.25"`，不能是 JSON number、科学记数、NaN 或无穷。

只应为构成一个连贯用户切换集合的 Metric 声明同一个 Group，例如 GitHub 项目的累计 Star 与距上次更新天数。即使单位、aggregation、Ranking 排序、display、description、summary 或 capability 不同，它们仍应是独立 Metric；Group 不会让这些属性共享。在顶层 `metric_groups` 声明一次 Group，再为每个成员提供相同的 `group_id`。这两个字段都是可选的：完全省略 Group 保持旧版平铺选择器；没有 `group_id` 的 Metric 仍为平铺条目且不参与 `m/M`。Group 标题会展示给用户，必须提供双语；空 Group 合法但 ccuv 不显示。

按用户语义而不是传输便利性选择 Filter mode。对于互斥模式和可理解的范围，应优先使用 `single_select`，例如“7 天以内”“30 天以内”“不限”：同时组合多个范围既有歧义又不便展示。只有用户确实需要组合独立离散值时才用 `multi_select`，例如语言、分类、标签、作者或书架标签。只有确实想使用兼容的 `multi_select` 默认值时才省略 `mode`。ccuv 中 `single_select` 可以为空；若必须选择，Dataset 应在查询时校验并返回可操作的本地化错误，不要猜测一个值。

历史 capability 声明 `granularities`、`group_by` 与可选有序 `periods`；若 Ranking 的源端永远无法提供更多原始排行项目，还可声明正整数 `max_items`。Ranking 可选 `comparison: "full" | "rank" | "none"`，默认 `full`；`rank` 保留前一等长周期请求与排名变化，但隐藏绝对增长；`none` 不请求前期且隐藏所有对比列。Metric 语义需要时，在 Ranking capability 声明 `sort_direction: "ascending" | "descending"`；省略即为降序。ccuv 用它处理 Ranking 顺序、Top N、Other 和排名对比，不提供宿主侧用户覆盖。数值越小越应先看的指标（如距上次更新天数）使用升序；Star、增长、评分或数量使用降序。为兼容旧版 Descriptor，Ranking 也可使用 `descriptions_default: "expanded" | "collapsed"`，但 ccuv 会忽略该字段。说明由密度决定：`full` 和 `detailed` 显示，`minimal`、`compact` 和 `normal` 隐藏。`group_by` 中的 JSON `null` 表示允许未分组总计。filter 不属于 Probe 的静态能力，而是在每一次成功查询的 `runtime.filters` 中声明。Monitor 必须声明固定正数 `window_seconds`，它定义每条 observation 的业务事实窗口；`refresh_interval_seconds` 只是建议采样频率。

## 每种查询如何处理

每个响应都必须原样回显请求的 `protocol`、`request_id`、`request_kind`、稳定 `dataset_id` 和 `status`。chart、monitor、summary 还必须回显相同的 `metric_id`。

### `chart`

请求给出时区、含首尾的 `range.start_date/end_date`、可选 `period`，以及 `query.filters/group_by/granularity/top`。日期范围权威且包含两端；`period` 仅是滚动范围上下文。`query.top` 可选，它统一表示用户希望显示的 Top N 与请求的原始排行覆盖量；若为诚实计算 `Other` 需要更多原始项目，Dataset 可以返回更多。`null` 表示不限制 Top。只接受自己 capability 声明过的选择。

成功响应包含完整 `descriptor`、`runtime:{"filters":[...]}` 和 `data.series`。每个 point 的 `date` 是 `YYYY-MM-DD`，`value` 是十进制字符串。Ranking series 还可使用与 `label` 相同的双语结构提供可选 `description` 与 `display`；ccuv 在 `full` 和 `detailed` 密度下将前者展示为最多两行、弱化颜色并带缩进的说明。description 支持 `[label](https://URL)`、`**粗体文字**` 与 `*斜体文字*`；链接显示为可点击的 `label`，其文字内也可使用星号格式。下划线格式、其他 Markdown 和不安全终端内容均按纯文本处理。`display` 是显示在数值列、由 Dataset 决定的总量文本；ccuv 仍根据十进制 point 计算排序、占比和比较。每个具体 Ranking 项还可提供一个可选 `link`，它必须是绝对 `https://` URL；ccuv 会在项目名后的操作区显示可点击的 `↗`（`项目 | ⊞ ↗`），并在复制该项目时附带 URL。对于非固定范围的 `full` / `detailed` Ranking，ccuv 会额外发起一次紧邻且等长的上一范围普通 chart 请求。请保持两次响应的 series ID 稳定，ccuv 据此自行计算绝对增长与排名变化；不要返回 delta 或前值字段。Timeline、Stack、Calendar 不得返回 `description`、`display` 或 `link`。有效范围没有事实时返回空 series，不要把未知事实伪造成零。

### `summary`

仅当 Metric 声明 `comparisons` 或 `total` 时 ccuv 才会发。请求中的 `summary.intervals` 已由 ccuv 按时区解析完成，必须直接使用，不能自行重新解释“本月”。不可用的环比/同比可返回 `{"status":"unavailable"}`；`summary: "none"` 表示此 Metric 不应请求 summary。

### `monitor`

请求只有带时区的 `range.end_at`，没有用户自选业务时长。按 capability 声明的固定 `window_seconds` 计算截止时刻前的源端总量和 group，返回完整 `descriptor`、`runtime:{"filters":[...]}`、aware `observation.end_at`、字符串 `total` 和可选 groups。无法回答精确窗口时返回 `status:"error"` 和 `code:"range_not_available"`，绝不能用零替代。defaults 中的 `window:"6h"` 只是 ccuv 本地显示历史范围，不改变源端 `window_seconds`。

### 错误与警告

不支持但格式正确的请求返回结构化 protocol error，而不是崩溃。可用 code：`unsupported_dataset`、`unsupported_chart_kind`、`unsupported_query`、`invalid_request`、`invalid_filter`、`range_not_available`、`source_unavailable`、`internal_error`。每个 error 有双语 message；不支持某项时加 `"unsupported":{"field":"query.group_by","value":"project"}`。成功响应可携带不阻塞的 `warnings`，每项也有稳定 code 与双语 message。

## 实际开发与测试顺序

1. 先定义度量语义：它测量什么、是否可加总、自然日边界、Monitor 固定窗口。
2. 用静态配置实现 Probe；用上面的 stdin 管道和 `jq` 检查 stdout。
3. 先完成一种历史图和固定范围；分组与 Ranking 只在 Decimal 总量正确后加入。
4. `ccuv dataset add-local ...` 注册；再运行 `ccuv dataset`，Enter 查看 Metric、支持图、环境变量、命令来源和状态。
5. 分别运行 standalone 和 Dashboard Pane；测试显式 filter/group/style/theme 与不支持选择。
6. 在自己的仓库写 fixture 测试：Probe、每种请求、非法 metric/filter/group、无数据范围、源端不可用、环境变量缺失。

## 打包、运行时依赖、GitHub 发布与官方目录

### 推荐：纯 Go 单二进制

优先采用纯 Go，并以 `CGO_ENABLED=0` 构建。Go module 会编入最终程序，因此用户机器无需安装 Go 或语言运行时。针对每个平台分别构建；Go 交叉编译非常直接：

```bash
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-darwin-arm64/bin/example-activity ./cmd/example-activity
CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-darwin-amd64/bin/example-activity ./cmd/example-activity
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-linux-amd64/bin/example-activity ./cmd/example-activity
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags='-s -w' -o dist/example-activity-windows-amd64/bin/example-activity.exe ./cmd/example-activity
```

`cgo`、C 驱动数据库、系统共享库或浏览器驱动会让产物依赖目标系统环境，不能再轻率地称为独立单文件。优先使用标准库网络能力和 pure Go 依赖。

### 如果确实依赖另一个二进制

先判断能否改为库依赖或直接调用 API；这才是首选，因为最终仍能保持单二进制。确实需要 companion binary 时，把版本匹配的 companion 和 Dataset 放进同一个平台 archive，让 Dataset 根据自身可执行文件位置找到它：

```text
manifest.json
bin/my-dataset
lib/vendor-client
```

两个二进制应随同一个 release 升级。companion 缺失或不能运行时，Dataset 返回带双语文案的 `source_unavailable`。不要只靠从 `PATH` 猜测依赖位置；可以作为明确文档化的 fallback，但会使部署不可复现。

如果因许可证、体积或厂商安装条件不能随包分发，则要求显式变量，例如 `MY_DATASET_CLIENT_BIN=/opt/vendor/client`。在 Probe 的 `environment` 中声明该变量；实际 Chart/Monitor 查询时验证它，不存在时返回可操作的双语 `source_unavailable`。

### 如果 Dataset 是 Python 或其他动态语言

Python、Node、Ruby 等完全可用于本地开发和私有部署。公开发布时不要假定用户和开发者有相同 runtime、venv 或已安装依赖。优先把适配器改写为纯 Go；必须保留动态语言代码时，用 PyInstaller/Nuitka（Python）等工具为**每个平台分别**打包 native executable，并像用户一样测试每个 artifact。它可行，但没有 Go 交叉编译这样直接。

本地开发不需要 archive。要分发则为每个 OS/arch 发布一个 `.tar.gz`，内容为：

```text
manifest.json
bin/my-dataset
```

manifest 包含 `schema:"ccuv.dataset/v1"`、`protocol:"ccuv.custom/v2"`、`entrypoint:"bin/my-dataset"`、`platform`，以及元数据或静态 Probe。可执行文件必须有 executable bit。asset 建议命名为 `example-activity-darwin-arm64.tar.gz`，并发布 `checksums.txt`、`sha256sums` 或 `sha256sums.txt`。

发布 Release 后，通过 `ccuv dataset` -> `+` -> **Install from GitHub** 输入 `OWNER/REPOSITORY` 测试。ccuv 会选择兼容 archive、校验 checksum、验证 manifest 并注册。官方身份是独立流程：仓库需进入 ccuv 的签名官方目录；公开 GitHub Release 即使不是官方也可安装。

## 交付检查表

- [ ] 一次 stdin 请求对应一次 stdout JSON；日志只写 stderr。
- [ ] Probe 纯元数据，所有显示文本双语。
- [ ] Dataset/Metric/unit/filter/option ID 稳定。
- [ ] 响应严格回显请求身份，数值均为十进制字符串。
- [ ] capability 只声明真正可回答的配置。
- [ ] 不支持请求返回结构化 error；Monitor 无法回答时返回 `range_not_available`。
- [ ] 已测试本地注册、standalone、Dashboard Pane 和 GitHub Release 安装。
