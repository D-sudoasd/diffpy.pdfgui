#!/usr/bin/env python
##############################################################################
#
# (c) 2024-2026 The Trustees of Columbia University in the City of New York.
# All rights reserved.
#
# File coded by: Pavol Juhas, Simon Billinge, Billinge Group members.
#
# See GitHub contributions for a more detailed list of contributors.
# https://github.com/diffpy/diffpy.pdfgui/graphs/contributors  # noqa: E501
#
# See LICENSE.rst for license information.
#
##############################################################################
"""Definition of __version__."""

#  We do not use the other three variables, but can be added back if needed.
#  __all__ = ["__date__", "__git_commit__", "__timestamp__", "__version__"]

# obtain version information
from importlib.metadata import PackageNotFoundError, version

from diffpy.pdfgui.branding import DISTRIBUTION_NAMES


def distribution_version(version_getter=version):
    """Return installed AI-PDFgui version with legacy metadata fallback."""

    for distribution_name in DISTRIBUTION_NAMES:
        try:
            return version_getter(distribution_name)
        except PackageNotFoundError:
            continue
    return "unknown"


__version__ = distribution_version()
