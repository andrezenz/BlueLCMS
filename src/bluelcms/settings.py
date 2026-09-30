"""Persistent desktop preferences, separate from analysis functionality."""

from pathlib import Path

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
