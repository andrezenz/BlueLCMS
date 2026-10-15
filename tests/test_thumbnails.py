import os
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image
from PySide6.QtGui import QImage

from bluelcms.folders import cleanup_expired_cache
from bluelcms.mzml import DADScan, Run, Scan, cache_has_previews, load_compact_cache, write_compact_cache
from bluelcms.thumbnails import PREVIEW_SIZES, cached_preview, preview_cache_path, render_preview
from test_mzml import write_mzml


def sample_run():
    return Run(
        dad=(DADScan(0, np.array([250., 254., 280.]), np.array([0., 5., 10.])),
             DADScan(1, np.array([250., 254., 280.]), np.array([3., 8., 4.]))),
        scans=(Scan(0, "+", np.array([100., 200.]), np.array([2., 5.])),
               Scan(1, "+", np.array([100., 200.]), np.array([4., 1.])),
               Scan(0, "-", np.array([100., 200.]), np.array([7., 3.]))),
        tic=((0, 7., "+"), (1, 5., "+"), (0, 10., "-")),
    )


def test_preview_uses_nearest_uv_and_valid_square_png_sizes():
    run = Run((DADScan(1, np.array([250., 270.]), np.array([2., 9.])),), (), 0)
    wavelength, times, values = __import__("bluelcms.thumbnails", fromlist=["nearest_uv_trace"]).nearest_uv_trace(run)
    assert wavelength == 250
    np.testing.assert_equal(times, [1])
    np.testing.assert_equal(values, [2])
    for size in PREVIEW_SIZES:
        image = QImage.fromData(render_preview(sample_run(), size), "PNG")
        assert not image.isNull()
        assert image.width() == image.height() == size


def test_preview_uses_light_background_and_distinct_dark_trace_colors():
    import io

    image = np.asarray(Image.open(io.BytesIO(render_preview(sample_run(), 256))).convert("RGB"))
    assert np.all(image[0, 0] > 240)
    for color in ((23, 105, 170), (24, 122, 69), (181, 47, 54)):
        assert np.any(np.all(image == color, axis=2))


def test_compact_cache_embeds_and_saves_all_preview_sizes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    source = tmp_path / "sample.mzML"
    source.write_bytes(b"test original")
    cache = tmp_path / "analysis" / "sample.bluelcms.npz"
    write_compact_cache(sample_run(), cache, '{"path": "' + str(source) + '"}')
    assert cache_has_previews(cache)
    with np.load(cache, allow_pickle=False) as data:
        for size in PREVIEW_SIZES:
            image = QImage.fromData(data[f"preview_{size}"].tobytes(), "PNG")
            assert image.width() == image.height() == size
            assert preview_cache_path(cache, size).is_file()
            assert cached_preview(cache, size) == data[f"preview_{size}"].tobytes()
    for directory in ("normal", "large", "x-large"):
        thumbs = list((tmp_path / "xdg-cache" / "thumbnails" / directory).glob("*.png"))
        assert len(thumbs) == 1
        assert not QImage(str(thumbs[0])).isNull()
        data = thumbs[0].read_bytes()
        assert b"Thumb::URI\0" + source.resolve().as_uri().encode() in data
        assert b"Thumb::MTime\0" in data


def test_backfill_preview_files_for_existing_cache(tmp_path):
    cache = write_compact_cache(sample_run(), tmp_path / "old.bluelcms.npz")
    assert cache_has_previews(cache)
    assert all(preview_cache_path(cache, size).is_file() for size in PREVIEW_SIZES)
    assert len(load_compact_cache(cache).dad) == 2


def test_old_cache_preview_format_is_detected_and_upgraded(tmp_path):
    original = write_compact_cache(sample_run(), tmp_path / "original.bluelcms.npz")
    outdated = tmp_path / "old-format.bluelcms.npz"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(outdated, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            if name != "preview_format.npy":
                target.writestr(name, source.read(name))
    assert not cache_has_previews(outdated)
    run = load_compact_cache(outdated)
    write_compact_cache(run, outdated)
    assert cache_has_previews(outdated)
    with np.load(outdated, allow_pickle=False) as data:
        assert int(data["preview_format"]) == 2


def test_headless_thumbnailer_generates_from_mzml_and_embedded_cache(tmp_path):
    source = write_mzml(tmp_path / "source.mzML")
    cache = write_compact_cache(__import__("bluelcms.mzml", fromlist=["load_run"]).load_run(source), tmp_path / "cached.bluelcms.npz")
    helper = Path(__file__).parents[1] / "packaging/linux/bluelcms-thumbnailer.py"
    for measurement in (source, cache):
        output = tmp_path / f"{measurement.name}.png"
        result = subprocess.run([sys.executable, str(helper), "256", str(measurement), str(output)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        image = QImage(str(output))
        assert image.width() == image.height() == 256
    # Nautilus/bubblewrap renames the source to a temporary basename that
    # retains only the final extension (e.g. gnome-desktop-file-to-thumbnail.npz).
    sandbox_cache = tmp_path / "gnome-desktop-file-to-thumbnail.npz"
    sandbox_cache.write_bytes(cache.read_bytes())
    output = tmp_path / "sandbox-cache.png"
    result = subprocess.run([sys.executable, str(helper), "128", str(sandbox_cache), str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert QImage(str(output)).width() == 128
    output = tmp_path / "source-via-app-cli.png"
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "launch.py"),
                             "--thumbnail", "128", str(source), str(output)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert QImage(str(output)).width() == 128


def test_headless_thumbnailer_reads_compressed_mzml(tmp_path):
    source = write_mzml(tmp_path / "source.mzML")
    import gzip
    compressed = tmp_path / "source.mzML.gz"
    with source.open("rb") as input_file, gzip.open(compressed, "wb") as output_file:
        output_file.write(input_file.read())
    helper = Path(__file__).parents[1] / "packaging/linux/bluelcms-thumbnailer.py"
    output = tmp_path / "compressed.png"
    result = subprocess.run([sys.executable, str(helper), "128", str(compressed), str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    image = QImage(str(output))
    assert image.width() == image.height() == 128


def test_stdlib_thumbnailer_uses_minutes_and_nearest_uv_channel(tmp_path):
    helper = Path(__file__).parents[1] / "packaging/linux/bluelcms-thumbnailer.py"
    spec = importlib.util.spec_from_file_location("bluelcms_stdlib_thumbnailer", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = write_mzml(tmp_path / "sample.mzML")
    series = module.arrays_from_mzml(str(source))
    assert series[0][1] == "UV 254 nm"
    assert series[0][2] == [(1.0, 12.0)]
    assert series[1][2] == [(1.0, 12.0)]
    assert series[2][2] == [(1.0, 15.0)]


def test_cache_expiry_removes_portable_preview_sidecars(tmp_path):
    cache_folder = tmp_path / "cache"
    cache = write_compact_cache(sample_run(), cache_folder / "sample-deadbeef.bluelcms.npz")
    previews = [preview_cache_path(cache, size) for size in PREVIEW_SIZES]
    assert all(path.is_file() for path in previews)
    import time
    import os
    expired = time.time() - 10 * 86400
    os.utime(cache, (expired, expired))
    assert cleanup_expired_cache(cache_folder, 1) == 1
    assert not cache.exists()
    assert all(not path.exists() for path in previews)


def test_linux_installer_registers_headless_nemo_thumbnailer(tmp_path):
    root = Path(__file__).parents[1]
    work = tmp_path / "package"
    home = tmp_path / "home"
    work.mkdir(); home.mkdir()
    (work / "BlueLCMS").mkdir()
    (work / "BlueLCMS/BlueLCMS").write_text("placeholder")
    for name in ("install.sh", "BlueLCMS.desktop", "bluelcms.svg", "bluelcms-mime.xml", "bluelcms-thumbnailer.py"):
        shutil.copy(root / "packaging/linux" / name, work / name)
    environment = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(tmp_path / "xdg-cache"))
    result = subprocess.run(["sh", "install.sh"], cwd=work, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    thumbnailer = home / ".local/share/thumbnailers/bluelcms.thumbnailer"
    content = thumbnailer.read_text()
    assert "TryExec=/usr/bin/python3" in content
    assert "--thumbnail" not in content
    assert "application/x-bluelcms-cache" in content
    assert "application/x-bluelcms-mzml-gzip" in content
    embedded = content.split("base64.b64decode('", 1)[1].split("')", 1)[0]
    import base64
    assert base64.b64decode(embedded) == (root / "packaging/linux/bluelcms-thumbnailer.py").read_bytes()
