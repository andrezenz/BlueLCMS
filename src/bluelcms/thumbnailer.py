"""Headless Nautilus thumbnailer and external PNG preview reader."""

import argparse
from pathlib import Path
import sys

from .mzml import load_run
from .thumbnails import cached_preview, render_preview


def thumbnail_file(source, output, size):
    source, output = Path(source), Path(output)
    size = max(16, min(1024, int(size)))
    if source.name.endswith(".bluelcms.npz"):
        try:
            png = cached_preview(source, size)
        except (KeyError, ValueError, OSError):
            # Older caches do not embed PNGs; render directly from their compact
            # scan data without opening BlueLCMS's GUI.
            png = render_preview(load_run(source), size)
    else:
        png = render_preview(load_run(source), size)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(png)
    return output


def main(arguments=None):
    parser = argparse.ArgumentParser(description="Generate a BlueLCMS chromatogram thumbnail")
    parser.add_argument("size", type=int, help="Maximum PNG edge requested by the file manager")
    parser.add_argument("input", help="mzML, gzip mzML, or BlueLCMS compact cache")
    parser.add_argument("output", help="PNG destination supplied by the file manager")
    options = parser.parse_args(arguments)
    try:
        thumbnail_file(options.input, options.output, options.size)
    except Exception as error:
        print(f"BlueLCMS thumbnail generation failed: {error}", file=sys.stderr)
        return 1
    return 0
