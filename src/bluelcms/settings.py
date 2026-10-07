"""Persistent desktop preferences, separate from analysis functionality."""

from pathlib import Path
import os

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


def show_tic() -> bool:
    return settings().value("show_tic", True, type=bool)


def set_show_tic(show: bool) -> None:
    settings().setValue("show_tic", show)


def cache_expiry_days() -> int:
    return settings().value("cache_expiry_days", 7, type=int)


def set_cache_expiry_days(days: int) -> None:
    settings().setValue("cache_expiry_days", days)


def integration_folder() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data_home / "BlueLCMS" / "integrations"
