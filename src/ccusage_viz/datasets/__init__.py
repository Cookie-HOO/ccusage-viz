"""Installable executable dataset support.

Dataset acquisition, rendering, and provider execution deliberately remain outside
this package.  This package only validates, installs, and resolves executable
artifacts for the existing custom-command provider.
"""

from ccusage_viz.datasets.service import DatasetService

__all__ = ("DatasetService",)
