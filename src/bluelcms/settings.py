"""Persistent desktop preferences, separate from analysis functionality."""

from pathlib import Path
import os
import math

from PySide6.QtCore import QSettings


def settings() -> QSettings:
    return QSettings("BlueLCMS", "BlueLCMS")


def data_folder() -> Path | None:
    value = settings().value("data_folder", "", type=str)
    return Path(value) if value else None


def set_data_folder(path: Path) -> None:
    settings().setValue("data_folder", str(path.resolve()))
    set_data_folders([path])


def data_folders() -> list[Path]:
    values = settings().value("data_folders", [])
    if isinstance(values, str):
        values = [values]
    folders = [Path(value) for value in values if value]
    return folders or ([data_folder()] if data_folder() else [])


def set_data_folders(paths: list[Path]) -> None:
    unique = list(dict.fromkeys(str(path.resolve()) for path in paths))
    settings().setValue("data_folders", unique)
    settings().setValue("data_folder", unique[0] if unique else "")


def cache_folder() -> Path | None:
    value = settings().value("cache_folder", "", type=str)
    return Path(value) if value else None


def set_cache_folder(path: Path) -> None:
    settings().setValue("cache_folder", str(path.resolve()))


def show_date_prefix() -> bool:
    return settings().value("show_date_prefix", True, type=bool)


def set_show_date_prefix(show: bool) -> None:
    settings().setValue("show_date_prefix", show)


def show_tic(polarity=None) -> bool:
    legacy = settings().value("show_tic", True, type=bool)
    if polarity is None:
        return legacy
    key = "show_tic_positive" if polarity == "+" else "show_tic_negative"
    return settings().value(key, legacy, type=bool)


def set_show_tic(show: bool, polarity=None) -> None:
    key = "show_tic" if polarity is None else "show_tic_positive" if polarity == "+" else "show_tic_negative"
    settings().setValue(key, show)


def cache_expiry_days() -> int:
    return settings().value("cache_expiry_days", 0, type=int)


def set_cache_expiry_days(days: int) -> None:
    settings().setValue("cache_expiry_days", days)


def auto_refresh_sources() -> bool:
    return settings().value("auto_refresh_sources", True, type=bool)


def set_auto_refresh_sources(enabled: bool) -> None:
    settings().setValue("auto_refresh_sources", enabled)


def alert_new_measurements() -> bool:
    return settings().value("alert_new_measurements", True, type=bool)


def set_alert_new_measurements(enabled: bool) -> None:
    settings().setValue("alert_new_measurements", enabled)


def snap_mass_cursor() -> bool:
    return settings().value("snap_mass_cursor", False, type=bool)


def set_snap_mass_cursor(enabled: bool) -> None:
    settings().setValue("snap_mass_cursor", enabled)


def mass_cursor_snap_unit() -> str:
    unit = settings().value("mass_cursor_snap_unit", "pixels", type=str)
    return unit if unit in ("mz", "pixels") else "pixels"


def set_mass_cursor_snap_unit(unit: str) -> None:
    if unit not in ("mz", "pixels"):
        raise ValueError("Snap units must be 'mz' or 'pixels'.")
    settings().setValue("mass_cursor_snap_unit", unit)


def mass_cursor_snap_range(unit: str | None = None) -> float:
    unit = unit or mass_cursor_snap_unit()
    if unit not in ("mz", "pixels"):
        raise ValueError("Snap units must be 'mz' or 'pixels'.")
    default = 5.0 if unit == "mz" else 10.0
    key = f"mass_cursor_snap_range_{unit}"
    if unit == "mz":
        return settings().value(key, settings().value("mass_cursor_snap_range", default, type=float), type=float)
    return settings().value(key, default, type=float)


def set_mass_cursor_snap_range(radius: float, unit: str | None = None) -> None:
    unit = unit or mass_cursor_snap_unit()
    if unit not in ("mz", "pixels") or radius <= 0:
        raise ValueError("Snap range must be positive and use m/z or pixels.")
    settings().setValue(f"mass_cursor_snap_range_{unit}", radius)
    if unit == "mz":
        settings().setValue("mass_cursor_snap_range", radius)


def extracted_tics() -> list[dict]:
    import json
    import math
    try:
        entries = json.loads(settings().value("extracted_tics", "[]", type=str))
    except (ValueError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    result = []
    for entry in entries:
        try:
            mass, radius = float(entry["mass"]), float(entry["radius"])
            if math.isfinite(mass) and mass > 0 and math.isfinite(radius) and radius > 0:
                result.append({"mass": mass, "radius": radius, "enabled": bool(entry.get("enabled", True))})
        except (TypeError, ValueError, KeyError):
            continue
    return result



def uv_spectrum_at_cursor() -> bool:
    return settings().value("uv_spectrum_at_cursor", False, type=bool)


def set_uv_spectrum_at_cursor(enabled: bool) -> None:
    settings().setValue("uv_spectrum_at_cursor", bool(enabled))

def dad_heatmap_sensitivity() -> int:
    stored = settings().value("dad_heatmap_sensitivity", None)
    if stored is None:
        stored = settings().value("dad_heatmap_range_percent", 100, type=int)
    return min(100, max(0, int(stored)))


def set_dad_heatmap_sensitivity(percent: int) -> None:
    if not 0 <= percent <= 100:
        raise ValueError("Heatmap sensitivity must be between 0 and 100 percent.")
    settings().setValue("dad_heatmap_sensitivity", percent)


def dad_heatmap_palette() -> str:
    palette = settings().value("dad_heatmap_palette", "gnuplot_pubu", type=str)
    return palette if palette in ("gnuplot_pubu", "viridis", "plasma", "inferno", "magma", "grey") else "gnuplot_pubu"


def set_dad_heatmap_palette(palette: str) -> None:
    if palette not in ("gnuplot_pubu", "viridis", "plasma", "inferno", "magma", "grey"):
        raise ValueError(f"Unsupported DAD heatmap palette: {palette}")
    settings().setValue("dad_heatmap_palette", palette)


def dad_heatmap_baseline() -> float:
    return settings().value("dad_heatmap_baseline", 0.0, type=float)


def set_dad_heatmap_baseline(baseline: float) -> None:
    if not math.isfinite(baseline):
        raise ValueError("Heatmap baseline must be finite.")
    settings().setValue("dad_heatmap_baseline", baseline)


def last_changelog_version() -> str:
    return settings().value("last_changelog_version", "", type=str)


def set_last_changelog_version(version: str) -> None:
    settings().setValue("last_changelog_version", version)


def set_extracted_tics(entries: list[dict]) -> None:
    import json
    settings().setValue("extracted_tics", json.dumps(entries, allow_nan=False))


def integration_folder() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data_home / "BlueLCMS" / "integrations"
