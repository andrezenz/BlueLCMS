"""Bug report helpers for opening GitHub issues from BlueLCMS."""

import json
import platform
import sys
from pathlib import Path
from urllib.parse import urlencode

from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPlainTextEdit,
    QLabel,
    QVBoxLayout,
    QCheckBox,
    QLineEdit,
)

from . import version


GITHUB_REPOSITORY = "andrezenz/BlueLCMS"
GITHUB_ISSUES_URL = f"https://github.com/{GITHUB_REPOSITORY}/issues/new"


def application_details(window=None):
    """Return non-path application diagnostics suitable for a public issue."""
    root = Path(__file__).resolve().parents[2]
    revision = None
    try:
        if (root / "pyproject.toml").is_file():
            revision = version.source_version(root)
    except (OSError, ValueError, TypeError):
        revision = None
    details = {
        "version": QApplication.applicationVersion() if QApplication.instance() else "unknown",
        "source_version": revision,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "qt": f"{platform.python_implementation()} {platform.architecture()[0]}",
    }
    if window is not None:
        try:
            details.update({
                "selected_measurements": len(window.files.selectedItems()) if hasattr(window, "files") else 0,
                "loaded_measurements": len(window.runs) if hasattr(window, "runs") else 0,
                "filters_active": bool(window.xic_entries) if hasattr(window, "xic_entries") else False,
            })
        except (AttributeError, RuntimeError, TypeError):
            pass
    return details


def format_environment(details):
    lines = [
        "## Environment",
        f"- BlueLCMS: {details.get('version', 'unknown')}",
    ]
    if details.get("source_version"):
        lines.append(f"- Source revision: {details['source_version']}")
    lines.extend([
        f"- Platform: {details.get('platform', 'unknown')}",
        f"- Python: {details.get('python', 'unknown')}",
        f"- Qt/PySide6: {details.get('qt', 'unknown')}",
    ])
    if details.get("selected_measurements") is not None:
        lines.append(f"- Selected measurements: {details['selected_measurements']}")
        lines.append(f"- Loaded measurements: {details['loaded_measurements']}")
    return "\n".join(lines)


def bug_report_body(title="", description="", include_environment=True, details=None, window=None):
    sections = []
    if title.strip():
        sections.append(f"## Summary\n{title.strip()}")
    if description.strip():
        sections.append(f"## Description\n{description.strip()}")
    if include_environment:
        sections.append(format_environment(details or application_details(window)))
    sections.append("## Expected behavior\n")
    sections.append("## Additional context\n")
    return "\n\n".join(section for section in sections if section.strip())


def github_issue_url(title="", body="", labels=None, repo=GITHUB_REPOSITORY):
    labels = labels or ("bug",)
    query = {
        "title": title or "Bug report from BlueLCMS",
        "labels": ",".join(str(label) for label in labels if label),
        "body": body,
    }
    return QUrl(f"{GITHUB_ISSUES_URL}?{urlencode(query)}")


github_issue_new_url = github_issue_url
issue_url = github_issue_url
build_github_issue_url = github_issue_url


class BugReportDialog(QDialog):
    def __init__(self, parent=None, title="", description="", include_environment=True):
        super().__init__(parent)
        self.setWindowTitle("Report a bug")
        self.resize(760, 560)
        self.title_edit = QLineEdit(self)
        self.title_edit.setText(title)
        self.title_edit.setPlaceholderText("Short summary")
        self.description_edit = QPlainTextEdit(self)
        self.description_edit.setPlaceholderText("What happened, what you expected, and how to reproduce it")
        self.description_edit.setPlainText(description)
        self.include_environment = QCheckBox("Include diagnostic environment information", self)
        self.include_environment.setChecked(include_environment)
        self.diagnostic_preview = QPlainTextEdit(self)
        self.diagnostic_preview.setReadOnly(True)
        self.diagnostic_preview.setPlainText("")
        self.button_box = QDialogButtonBox(self)
        self.open_button = self.button_box.addButton("Open on GitHub", QDialogButtonBox.ButtonRole.AcceptRole)
        self.copy_button = self.button_box.addButton("Copy diagnostics", QDialogButtonBox.ButtonRole.ActionRole)
        self.button_box.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.rejected.connect(self.reject)
        self.copy_button.clicked.connect(self.copy_diagnostics)
        self.include_environment.toggled.connect(self.refresh_diagnostics)
        self.title_edit.textChanged.connect(self.refresh_diagnostics)
        self.description_edit.textChanged.connect(self.refresh_diagnostics)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("Title", self.title_edit)
        form.addRow("Description", self.description_edit)
        layout.addLayout(form)
        layout.addWidget(self.include_environment)
        layout.addWidget(QLabel("Diagnostics included in the report"))
        layout.addWidget(self.diagnostic_preview)
        layout.addWidget(self.button_box)
        self.update_parent = parent
        self.refresh_diagnostics()

    def values(self):
        return self.title_edit.text(), self.description_edit.toPlainText(), self.include_environment.isChecked()

    def refresh_diagnostics(self):
        window = self.update_parent
        title, description, include = self.values()
        body = bug_report_body(title, description, include_environment=include, window=window)
        self.diagnostic_preview.setPlainText(body)
        self.open_button.setEnabled(bool(title.strip() or description.strip() or include))

    def copy_diagnostics(self):
        application = QApplication.instance()
        if application is not None:
            application.clipboard().setText(self.diagnostic_preview.toPlainText())
