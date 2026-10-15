#!/usr/bin/python3
"""Small stdlib-only GNOME thumbnail helper; executed inline in thumbnail sandbox.

The installed .thumbnailer embeds this file into a python -c command. Thus the
helper itself lives in /usr/bin/python3, where Nautilus's bubblewrap sandbox can
run it, while it reads only the measurement supplied as the input argument.
"""

import base64
import gzip
import math
import struct
import sys
import zipfile
import zlib
from xml.etree import ElementTree


SIZES = (128, 256, 512)
COLORS = {"uv": (23, 105, 170), "+": (74, 140, 102), "-": (196, 106, 110)}
GLYPHS = {
    "U": ("101", "101", "101", "101", "111"), "V": ("101", "101", "101", "101", "010"),
    "M": ("101", "111", "111", "101", "101"), "S": ("111", "100", "111", "001", "111"),
    "T": ("111", "010", "010", "010", "010"), "I": ("111", "010", "010", "010", "111"),
    "C": ("111", "100", "100", "100", "111"), "n": ("000", "110", "101", "101", "101"),
    "m": ("000", "110", "101", "101", "101"), "+": ("000", "010", "111", "010", "000"),
    "-": ("000", "000", "111", "000", "000"), " ": ("000", "000", "000", "000", "000"),
    **{str(number): glyph for number, glyph in enumerate((
        ("111", "101", "101", "101", "111"), ("010", "110", "010", "010", "111"),
        ("111", "001", "111", "100", "111"), ("111", "001", "111", "001", "111"),
        ("101", "101", "111", "001", "001"), ("111", "100", "111", "001", "111"),
        ("111", "100", "111", "101", "111"), ("111", "001", "010", "010", "010"),
        ("111", "101", "111", "101", "111"), ("111", "101", "111", "001", "111")))},
}


def npy_bytes(archive, name):
    data = archive.read(name)
    if data[:6] != b"\x93NUMPY":
        raise ValueError("invalid embedded preview array")
    major, minor = data[6], data[7]
    header_size, offset = (struct.unpack_from("<H", data, 8)[0], 10) if major == 1 else (struct.unpack_from("<I", data, 8)[0], 12)
    header = data[offset:offset + header_size].decode("latin1")
    if "'descr': '|u1'" not in header and '"descr": "|u1"' not in header:
        raise ValueError("embedded preview is not a byte array")
    return data[offset + header_size:]


def embedded_cache_png(path, size):
    with zipfile.ZipFile(path) as archive:
        name = f"preview_{size}.npy"
        if name not in archive.namelist():
            return None
        return npy_bytes(archive, name)


def arrays_from_mzml(path):
    opener = gzip.open if path.lower().endswith(".gz") else open
    dads, tics = [], {"+": [], "-": []}
    with opener(path, "rb") as stream:
        for _, spectrum in ElementTree.iterparse(stream, events=("end",)):
            if spectrum.tag.rsplit("}", 1)[-1] != "spectrum":
                continue
            params = [item.attrib for item in spectrum.iter() if item.tag.rsplit("}", 1)[-1] == "cvParam"]
            by_accession = {p.get("accession"): p for p in params}
            try:
                raw_time = float(by_accession["MS:1000016"]["value"])
            except (KeyError, TypeError, ValueError):
                spectrum.clear()
                continue
            unit = by_accession["MS:1000016"].get("unitAccession")
            if unit == "UO:0000031":
                time = raw_time
            elif unit == "UO:0000032":
                time = raw_time * 60
            elif unit == "UO:0000028":
                time = raw_time / 60000
            else:
                time = raw_time / 60
            arrays = {}
            for array in spectrum.iter():
                if array.tag.rsplit("}", 1)[-1] != "binaryDataArray":
                    continue
                terms = [item.attrib for item in array if item.tag.rsplit("}", 1)[-1] == "cvParam"]
                accession = next((p.get("accession") for p in terms if p.get("accession") in ("MS:1000514", "MS:1000515", "MS:1000617")), None)
                binary = next((item.text or "" for item in array if item.tag.rsplit("}", 1)[-1] == "binary"), "")
                if accession is None or not binary:
                    continue
                raw = base64.b64decode(binary)
                if any(p.get("accession") == "MS:1000574" for p in terms):
                    raw = zlib.decompress(raw)
                width = 4 if any(p.get("accession") == "MS:1000521" for p in terms) else 8 if any(p.get("accession") == "MS:1000523" for p in terms) else 0
                if width == 0:
                    continue
                endian = ">" if any(p.get("accession") == "MS:1000140" for p in terms) else "<"
                count = len(raw) // width
                values = [v[0] for v in struct.iter_unpack(endian + ("f" if width == 4 else "d"), raw[:count * width])]
                arrays[accession] = values
            if "MS:1000806" in by_accession:
                if "MS:1000617" in arrays and "MS:1000515" in arrays:
                    dads.append((time, arrays["MS:1000617"], arrays["MS:1000515"]))
            elif by_accession.get("MS:1000511", {}).get("value") == "1":
                polarity = "+" if "MS:1000130" in by_accession else "-" if "MS:1000129" in by_accession else None
                if polarity and "MS:1000515" in arrays:
                    tics[polarity].append((time, sum(v for v in arrays["MS:1000515"] if math.isfinite(v))))
            spectrum.clear()
    wavelengths = [value for _, axis, _ in dads for value in axis if math.isfinite(value)]
    target = min(wavelengths, key=lambda value: abs(value - 254)) if wavelengths else 254
    uv = []
    for time, axis, values in dads:
        count = min(len(axis), len(values))
        choices = [index for index in range(count) if math.isfinite(axis[index]) and math.isfinite(values[index])]
        if choices:
            index = min(choices, key=lambda i: abs(axis[i] - target))
            uv.append((time, values[index]))
    return [("uv", f"UV {target:g} nm", uv), ("+", "MS TIC (+)", tics["+"]), ("-", "MS TIC (-)", tics["-"])]


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


def draw_preview(series, size):
    pixels = bytearray([247, 249, 251] * (size * size))
    margin = max(5, round(size * .075))
    legend = max(30, round(size * .29))
    left, right, top, bottom = margin, size - margin, margin, size - margin - legend
    width, height = right - left, bottom - top

    stroke = max(2, round(size / 96))
    legend_y = bottom + max(3, round(size * .035))
    glyph_scale = max(1, round(size / 128))

    def dot(x, y, color, width=1):
        radius = (width - 1) // 2
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < size and 0 <= yy < size:
                    offset = (yy * size + xx) * 3
                    pixels[offset:offset + 3] = bytes(color)

    def line(x0, y0, x1, y1, color, width=1):
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error = dx - dy
        while True:
            dot(x0, y0, color, width)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * error
            if twice > -dy:
                error -= dy; x0 += sx
            if twice < dx:
                error += dx; y0 += sy

    def text(x, y, label, color):
        cursor = x
        for character in label:
            glyph = GLYPHS.get(character, GLYPHS[" "])
            for row, bits in enumerate(glyph):
                for column, bit in enumerate(bits):
                    if bit == "1":
                        for yy in range(glyph_scale):
                            for xx in range(glyph_scale):
                                dot(cursor + column * glyph_scale + xx, y + row * glyph_scale + yy, color)
            cursor += 4 * glyph_scale

    for index in range(1, 5):
        x = left + width * index // 4
        y = top + height * index // 4
        for point in range(top, bottom):
            dot(x, point, (220, 226, 231))
        for point in range(left, right):
            dot(point, y, (220, 226, 231))

    all_times = [time for _, _, points in series for time, value in points if math.isfinite(time) and math.isfinite(value)]
    time_min, time_max = (min(all_times), max(all_times)) if all_times else (0., 1.)
    if time_max <= time_min:
        time_max = time_min + 1
    for kind, _, points in series:
        values = [(time, value) for time, value in points if math.isfinite(time) and math.isfinite(value)]
        values.sort()
        if not values:
            continue
        low, high = min(value for _, value in values), max(value for _, value in values)
        previous = None
        for time, value in values:
            x = round(left + (time - time_min) / (time_max - time_min) * width)
            normalized = .5 if high <= low else (value - low) / (high - low)
            y = round(bottom - normalized * height)
            if previous is not None:
                line(previous[0], previous[1], x, y, COLORS[kind], stroke)
            previous = (x, y)

    for index, (kind, label, _) in enumerate(series):
        y = legend_y + index * max(1, legend // 3)
        line(left + 2, y + 2 * glyph_scale, left + 8 * glyph_scale, y + 2 * glyph_scale, COLORS[kind], stroke)
        short_label = f"UV{label.split()[1]}nm" if kind == "uv" else f"MS{kind}"
        text(left + 10 * glyph_scale, y, short_label, (23, 36, 46))

    raw = b"".join(b"\0" + pixels[row * size * 3:(row + 1) * size * 3] for row in range(size))
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + png_chunk(b"IDAT", zlib.compress(raw, 6)) + png_chunk(b"IEND", b"")


def render_mzml_thumbnail(path, size):
    size = min(SIZES, key=lambda candidate: abs(candidate - size))
    return draw_preview(arrays_from_mzml(path), size)


def main():
    try:
        # For `python -c CODE %s %i %o`, the first placeholder is sys.argv[0];
        # this offset also permits direct invocation while developing/testing.
        offset = 0 if sys.argv[0].isdigit() else 1
        size, source, output = int(sys.argv[offset]), sys.argv[offset + 1], sys.argv[offset + 2]
        if zipfile.is_zipfile(source):
            png = embedded_cache_png(source, min(SIZES, key=lambda item: abs(item - size)))
            if png is None:
                raise ValueError("BlueLCMS cache has no embedded chromatogram preview")
        else:
            png = render_mzml_thumbnail(source, size)
        with open(output, "wb") as handle:
            handle.write(png)
        return 0
    except Exception as error:
        print(f"BlueLCMS thumbnailer: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
