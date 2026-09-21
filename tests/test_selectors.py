import pytest

from ccusage_viz.errors import UsageError
from ccusage_viz.selectors import SelectorCandidate, resolve_selectors


def candidates():
    return (
        SelectorCandidate("a", "alpha", ("Alpha",)),
        SelectorCandidate("b", "alphabet", ("Alphabet",)),
        SelectorCandidate("c", "beta", ("Beta",)),
    )


def test_complete_case_insensitive_matches_are_or_and_deduplicated() -> None:
    assert resolve_selectors(("ALPHA", "BETA", "alpha"), candidates(), dimension="model") == (
        "alpha",
        "beta",
    )


def test_partial_and_missing_selectors_raise_a_no_match_error() -> None:
    for selector in ("alph", "phabet", "omega"):
        with pytest.raises(UsageError) as missing:
            resolve_selectors((selector,), candidates(), dimension="model")
        assert missing.value.key == "error.selector_no_match"
        assert missing.value.values == {"selector": selector, "dimension": "model"}
