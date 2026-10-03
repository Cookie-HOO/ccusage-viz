from ccusage_viz.custom_filter_draft import run_custom_filter_editor
from ccusage_viz.custom_models import CustomFilter, CustomFilterOption, LocalizedText
from ccusage_viz.i18n import load_translator

CHOICES = (
    CustomFilter(
        "category",
        LocalizedText("Category", "分类"),
        (
            CustomFilterOption("fiction", LocalizedText("Fiction", "小说")),
            CustomFilterOption("history", LocalizedText("History", "历史")),
        ),
    ),
    CustomFilter(
        "source",
        LocalizedText("Source", "来源"),
        (CustomFilterOption("app", LocalizedText("App", "应用")),),
    ),
)


def test_custom_filter_editor_toggles_declared_option_ids_and_drops_empty_filters() -> None:
    events = iter((" ", "l", " ", "\r"))

    result = run_custom_filter_editor(
        (("category", ("fiction",)),),
        CHOICES,
        load_translator("en"),
        width=80,
        paint=lambda _body, _controls: None,
        read_key=lambda: next(events),
    )

    assert result == (("source", ("app",)),)


def test_custom_filter_editor_renders_protocol_localized_labels() -> None:
    rendered: list[str] = []
    events = iter(("\x1b",))

    result = run_custom_filter_editor(
        (),
        CHOICES,
        load_translator("zh"),
        width=80,
        paint=lambda body, _controls: rendered.append(body),
        read_key=lambda: next(events),
    )

    assert result is None
    assert "[分类]" in rendered[0]
    assert "小说" in rendered[0]
