from types import SimpleNamespace

from ccusage_viz.custom_models import LocalizedText


def _catalog_entries(count: int = 1) -> tuple[object, ...]:
    return tuple(
        SimpleNamespace(
            id=f"dataset-{index}",
            title=LocalizedText(f"Dataset {index}", f"数据集 {index}"),
            summary=LocalizedText(
                "This deliberately long summary explains what the Dataset measures over a useful period and adds enough detail to require truncation after two lines.",
                "这是一个用于验证官方数据集简介最多显示两行并在超出时省略的较长说明，同时增加足够内容以确保窄窗口需要截断。",
            ),
        )
        for index in range(count)
    )
