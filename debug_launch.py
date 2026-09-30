#!/usr/bin/env python3
"""Run BlueLCMS in a terminal and retain stdout/stderr after it exits."""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parent
    result = subprocess.run([sys.executable, str(root / "launch.py")])
    print(f"\nBlueLCMS exited with code {result.returncode}.")
    try:
        input("Press Enter to close this terminal…")
    except EOFError:
        pass
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
