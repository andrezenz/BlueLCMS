"""Persistent charge-envelope search settings."""

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                              QFormLayout, QLabel, QMessageBox, QSpinBox)

from .deconvolution import DeconvolutionSettings


class DeconvolutionDialog(QDialog):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Oligonucleotide deconvolution")
        layout = QFormLayout(self)
        self.fields = {}
        for name, label, minimum, maximum, decimals, suffix in (
                ("minimum_mass", "Lower neutral mass", 1, 1e7, 2, " Da"),
                ("maximum_mass", "Upper neutral mass", 1, 1e7, 2, " Da"),
                ("minimum_charge", "Lower charge magnitude", 1, 100, None, ""),
                ("maximum_charge", "Upper charge magnitude", 1, 100, None, ""),
                ("tolerance", "Peak-matching tolerance", .001, 2, 3, " Th"),
                ("minimum_signal_percent", "Minimum peak height", .001, 100, 3, " % of highest peak"),
                ("minimum_support", "Minimum supporting charge states", 2, 100, None, "")):
            field = QSpinBox() if decimals is None else QDoubleSpinBox()
            if decimals is not None:
                field.setDecimals(decimals)
            field.setRange(minimum, maximum)
            field.setSuffix(suffix)
            field.setValue(getattr(options, name))
            self.fields[name] = field
            layout.addRow(label, field)
        note = QLabel("Proton-only envelope mass estimates; not monoisotopic or adduct assignments.\n"
                      "Default tolerance targets unresolved/low-resolution spectra. Native interval\n"
                      "bins are 0.03125 Th; tolerances below that may miss matches.\n"
                      "Relative abundance is assigned ion signal, separately per measurement/polarity.")
        note.setWordWrap(True)
        layout.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def selected_options(self):
        return DeconvolutionSettings(**{name: field.value() for name, field in self.fields.items()})

    def accept(self):
        try:
            self.selected_options()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid deconvolution settings", str(error))
            return
        super().accept()
