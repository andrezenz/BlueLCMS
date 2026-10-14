"""Offline documentation bundled with source, wheel, and executable installs."""

from importlib.resources import files

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout


def document_text(name):
    return files("bluelcms").joinpath(name).read_text(encoding="utf-8")


class DocumentDialog(QDialog):
    def __init__(self, title, document, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 600)
        self.browser = QTextBrowser(self)
        self.browser.setOpenExternalLinks(True)
        self.browser.setMarkdown(document_text(document))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.browser)
        layout.addWidget(buttons)
