# =============================================================================
# FILE:    farm/__init__.py
# PURPOSE: Marks `farm` as a package and holds the version string.
#
# DESIGN NOTES:
#   Nothing else lives here on purpose. Every number that matters is computed
#   in exactly one module (see stats.py), and every setting is read in one
#   place (see config.py).
# =============================================================================

__version__ = "0.1.0"
