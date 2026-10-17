import pytest

from ccusage_viz.domain import TokenUsage, model_identity


def test_token_usage_preserves_stack_compatible_other_total() -> None:
    usage = TokenUsage.from_parts(total=20, input=3, output=4, cache_read=5, cache_creation=6)
    assert usage.other == 2
    assert usage.total == sum(
        (usage.input, usage.output, usage.cache_read, usage.cache_creation, usage.other)
    )


@pytest.mark.parametrize("field", ["total", "input", "output", "cache_read", "cache_creation"])
def test_token_usage_rejects_negative_values(field: str) -> None:
    values = dict(total=4, input=1, output=1, cache_read=1, cache_creation=1)
    values[field] = -1
    with pytest.raises(ValueError):
        TokenUsage.from_parts(**values)


def test_token_usage_rejects_components_above_total() -> None:
    with pytest.raises(ValueError, match="exceed"):
        TokenUsage.from_parts(total=3, input=1, output=1, cache_read=1, cache_creation=1)


def test_token_usage_difference_returns_delta_or_counter_reset() -> None:
    previous = TokenUsage.from_parts(
        total=100, input=30, output=30, cache_read=20, cache_creation=10
    )
    current = TokenUsage.from_parts(
        total=160, input=50, output=40, cache_read=35, cache_creation=15
    )

    assert current.difference(previous) == TokenUsage(60, 20, 10, 15, 5, 10)
    assert previous.difference(current) is None


def test_model_identity_removes_only_leading_source_prefixes() -> None:
    assert model_identity("[pi] GPT-5.6-Terra") == "gpt-5.6-terra"
    assert model_identity("gpt-5.6 [pi]") == "gpt-5.6 [pi]"
    assert model_identity("[pi]gpt-5.6-terra") == "[pi]gpt-5.6-terra"
