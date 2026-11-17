"""Restore the host library search path for external system programs."""

import os
import sys


def system_environment(environment=None):
    """Undo PyInstaller's Linux LD_LIBRARY_PATH changes without mutating os.environ."""
    result = dict(os.environ if environment is None else environment)
    if sys.platform.startswith("linux") and (getattr(sys, "frozen", False) or "LD_LIBRARY_PATH_ORIG" in result):
        original = result.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            result.pop("LD_LIBRARY_PATH", None)
        else:
            result["LD_LIBRARY_PATH"] = original
    return result
