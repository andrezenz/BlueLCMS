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


def integration_folder() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data_home / "BlueLCMS" / "integrations"
