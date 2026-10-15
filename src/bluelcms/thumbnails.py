"""Render portable, small UV and polarity-specific TIC previews."""

from pathlib import Path
import hashlib
import json
import os
import struct
import time
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont


PREVIEW_SIZES = (128, 256, 512)
PREVIEW_FORMAT = 2
PREVIEW_COLORS = {"uv": "#1769aa", "+": "#187a45", "-": "#b52f36"}


def nearest_uv_trace(run, target=254.0):
    wavelengths = run.uv_wavelengths()
    if not len(wavelengths):
        return float(target), np.array([]), np.array([])
    wavelength = float(wavelengths[np.argmin(np.abs(wavelengths - target))])
    times, intensities, _ = run.uv_trace(wavelength)
    return wavelength, times, intensities


def preview_series(run):
    wavelength, uv_times, uv_values = nearest_uv_trace(run, 254.0)
    series = [("uv", f"UV {wavelength:g} nm", uv_times, uv_values)]
    tic = {"+": {}, "-": {}}
    for time, intensity, polarity in run.tic_points():
        if polarity in tic:
            tic[polarity][float(time)] = tic[polarity].get(float(time), 0.0) + float(intensity)
    for polarity, label in (("+", "MS TIC (+)"), ("-", "MS TIC (-)")):
        points = sorted(tic[polarity].items())
        values = np.asarray(points, dtype=float).reshape(-1, 2)
        series.append((polarity, label, values[:, 0], values[:, 1]))
    return series


def render_preview(run, size=128):
    """Create a square PNG with independently normalized, overlaid traces."""
    if not isinstance(size, int) or not 16 <= size <= 1024:
        raise ValueError("Preview size must be between 16 and 1024 pixels")
    image = Image.new("RGB", (size, size), "#f7f9fb")
    painter = ImageDraw.Draw(image)
    margin = max(5, round(size * .075))
    legend_height = max(30, round(size * .29))
    left, right = margin, size - margin
    top, bottom = margin, size - margin - legend_height
    plot_width, plot_height = right - left, bottom - top

    grid = "#dce2e7"
    for index in range(5):
        x = round(left + plot_width * index / 4)
        painter.line((x, top, x, bottom), fill=grid, width=max(1, round(size / 256)))
    for index in range(4):
        y = round(top + plot_height * index / 3)
        painter.line((left, y, right, y), fill=grid, width=max(1, round(size / 256)))
    painter.line((left, bottom, right, bottom), fill="#87939c", width=max(1, round(size / 256)))

    series = preview_series(run)
    all_times = [np.asarray(times, dtype=float) for _, _, times, values in series if len(times) and len(values)]
    time_min = min((float(times.min()) for times in all_times), default=0.0)
    time_max = max((float(times.max()) for times in all_times), default=1.0)
    if time_max <= time_min:
        time_max = time_min + 1.0

    for kind, label, times, values in series:
        times, values = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
        finite = np.isfinite(times) & np.isfinite(values)
        times, values = times[finite], values[finite]
        if not len(times):
            continue
        order = np.argsort(times, kind="stable")
        times, values = times[order], values[order]
        low, high = float(values.min()), float(values.max())
        normalized = np.full(len(values), .5) if high <= low else (values - low) / (high - low)
        points = [(round(left + (time - time_min) / (time_max - time_min) * plot_width),
                   round(bottom - value * plot_height)) for time, value in zip(times, normalized)]
        stroke = max(2, round(size / 96))
        if kind == "uv":
            painter.line(points, fill=PREVIEW_COLORS[kind], width=stroke)
        else:
            dash = max(2, round(size / 64))
            for first, second in zip(points, points[1:]):
                distance = max(1, round(np.hypot(second[0] - first[0], second[1] - first[1])))
                for start in range(0, distance, dash * 2):
                    end = min(distance, start + dash)
                    segment = tuple(round(first[i] + (second[i] - first[i]) * t / distance) for t in (start, end) for i in (0, 1))
                    painter.line(segment, fill=PREVIEW_COLORS[kind], width=stroke)

    font = ImageFont.load_default(size=max(7, round(size * .07)))
    row_height = legend_height / 3
    for index, (kind, label, _, _) in enumerate(series):
        x = left + max(2, round(size * .02))
        legend_y = bottom + row_height * (index + .5)
        painter.line((x, round(legend_y), x + max(8, size * .055), round(legend_y)),
                     fill=PREVIEW_COLORS[kind], width=max(2, round(size / 96)))
        painter.text((x + max(11, size * .075), round(legend_y - font.size / 2)), label, font=font, fill="#17242e")
    from io import BytesIO
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def preview_cache_path(cache, size):
    if size not in PREVIEW_SIZES:
        raise ValueError(f"Preview size must be one of {PREVIEW_SIZES}")
    return cache.parent / "previews" / f"{cache.stem}-{size}.png"


def save_preview_files(cache, previews):
    """Atomically expose preview PNG sidecars beside the compact-cache folder."""
    saved = []
    for size, content in previews.items():
        path = preview_cache_path(cache, size)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        temporary = path.with_name(f".{path.name}.part")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
            os.chmod(path, 0o600)
            saved.append(path)
        finally:
            temporary.unlink(missing_ok=True)
    return tuple(saved)


def _png_text_chunk(keyword, value):
    payload = keyword.encode("latin-1") + b"\0" + value.encode("utf-8")
    return struct.pack(">I", len(payload)) + b"tEXt" + payload + struct.pack(">I", zlib.crc32(b"tEXt" + payload) & 0xffffffff)


def _add_png_text(png, entries):
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG image")
    insert = 8
    chunks = []
    while insert < len(png):
        length = struct.unpack_from(">I", png, insert)[0]
        kind = png[insert + 4:insert + 8]
        end = insert + 12 + length
        chunks.append(png[insert:end])
        insert = end
        if kind == b"IHDR":
            chunks.extend(_png_text_chunk(key, value) for key, value in entries.items())
    return png[:8] + b"".join(chunks)


def write_desktop_thumbnail(source, previews):
    """Prime the standard XDG thumbnail cache so Files can reuse previews."""
    source = Path(source)
    try:
        stat = source.stat()
        uri = source.resolve().as_uri()
    except OSError:
        return ()
    data_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    sizes = {128: "normal", 256: "large", 512: "x-large"}
    saved = []
    for size, directory in sizes.items():
        if size not in previews:
            continue
        target_dir = data_home / "thumbnails" / directory
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.md5(uri.encode("utf-8"), usedforsecurity=False).hexdigest()
        target = target_dir / f"{digest}.png"
        temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
        try:
            metadata = {
                "Thumb::URI": uri,
                "Thumb::MTime": str(int(stat.st_mtime)),
                "Thumb::Size": str(stat.st_size),
                "Thumb::Mimetype": "application/x-bluelcms-mzml-gzip" if source.suffix.lower() == ".gz" else "application/x-bluelcms-mzml",
            }
            temporary.write_bytes(_add_png_text(previews[size], metadata))
            temporary.replace(target)
            os.chmod(target_dir, 0o700)
            os.chmod(target, 0o600)
            saved.append(target)
        finally:
            temporary.unlink(missing_ok=True)
    return tuple(saved)


def cached_preview(path, size):
    """Read an embedded image, or render from an older compact cache on demand."""
    if size not in PREVIEW_SIZES:
        size = min(PREVIEW_SIZES, key=lambda candidate: abs(candidate - size))
    with np.load(path, allow_pickle=False) as data:
        key = f"preview_{size}"
        preview_format = int(data["preview_format"]) if "preview_format" in data else 1
        if key in data and preview_format == PREVIEW_FORMAT:
            return data[key].tobytes()
    from .mzml import load_compact_cache
    return render_preview(load_compact_cache(path), size)
