#!/usr/bin/env python3
"""Launch the current checkout rather than a copied or globally installed package."""

from pathlib import Path
import runpy
import sys


def main():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "src"))
    runpy.run_module("bluelcms", run_name="__main__")


if __name__ == "__main__":
    main()
