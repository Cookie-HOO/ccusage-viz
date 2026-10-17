import pytest

from ccusage_viz.animation import animation_spec
from ccusage_viz.i18n import load_translator
from ccusage_viz.options import AnimationLaunch, ProcessConfig, StandaloneHostConfig


@pytest.fixture
def translator():
    return load_translator("en")


@pytest.fixture
def animation_launch() -> AnimationLaunch:
    return AnimationLaunch(ProcessConfig(), StandaloneHostConfig(), animation_spec("rain"))
