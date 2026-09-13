import pytest

from ccusage_viz.errors import UsageError
from ccusage_viz.selectors import SelectorCandidate, resolve_selectors


def candidates():
    return (
        SelectorCandidate("a", "alpha", ("Alpha",)),
        SelectorCandidate("b", "alphabet", ("Alphabet",)),
        SelectorCandidate("c", "beta", ("Beta",)),
    )


def test_exact_match_wins_before_contains() -> None:
    assert resolve_selectors(("alpha",), candidates(), dimension="model") == ("alpha",)


def test_unique_contains_and_or_across_repeated_selectors() -> None:
    assert resolve_selectors(("phabet", "BETA"), candidates(), dimension="model") == (
        "alphabet",
        "beta",
    )


def test_ambiguous_contains_and_no_match_raise_localizable_errors() -> None:
    with pytest.raises(UsageError) as ambiguous:
        resolve_selectors(("alph",), candidates(), dimension="model")
    assert ambiguous.value.key == "error.selector_ambiguous"
    assert ambiguous.value.values == {
        "selector": "alph",
        "dimension": "model",
        "candidates": "  - Alpha\n  - Alphabet",
    }
    many = tuple(
        SelectorCandidate(str(index), f"alpha-{index}", (f"Alpha {index}",)) for index in range(8)
    )
    with pytest.raises(UsageError) as truncated:
        resolve_selectors(("alpha",), many, dimension="model")
    assert truncated.value.key == "error.selector_ambiguous_more"
    assert truncated.value.values["remaining"] == 3
    candidates_value = truncated.value.values["candidates"]
    assert isinstance(candidates_value, str)
    assert candidates_value.count("\n") == 4

    with pytest.raises(UsageError) as missing:
        resolve_selectors(("omega",), candidates(), dimension="model")
    assert missing.value.key == "error.selector_no_match"
