"""Folder-organized measurement sidebar with leaf-only selection."""

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QApplication, QStyle, QTreeWidget, QTreeWidgetItem


class MeasurementItem(QTreeWidgetItem):
    """Single-column item with convenient measurement accessors."""

    def __init__(self, text=""):
        super().__init__([text])

    def data(self, *args):
        return super().data(0, args[0]) if len(args) == 1 else super().data(*args)

    def setData(self, *args):
        return super().setData(0, *args) if len(args) == 2 else super().setData(*args)

    def text(self, column=0):
        return super().text(column)

    def setText(self, *args):
        return super().setText(0, args[0]) if len(args) == 1 else super().setText(*args)

    def toolTip(self, column=0):
        return super().toolTip(column)

    def setToolTip(self, *args):
        return super().setToolTip(0, args[0]) if len(args) == 1 else super().setToolTip(*args)

    def setIcon(self, *args):
        return super().setIcon(0, args[0]) if len(args) == 1 else super().setIcon(*args)


class MeasurementTree(QTreeWidget):
    """Count and iterate measurement leaves independently of folder nodes."""

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.roots = ()
        self._folders = {}
        self._items = []

    def set_roots(self, roots):
        self.roots = tuple(sorted(set(roots), key=lambda path: len(path.parts), reverse=True))

    def folder_expansion(self):
        return {path: item.isExpanded() for path, item in self._folders.items()}

    def restore_folder_expansion(self, states):
        for path, expanded in states.items():
            if path in self._folders:
                self._folders[path].setExpanded(expanded)

    def clear(self):
        self._folders.clear()
        self._items.clear()
        super().clear()

    def _folder(self, path, label, parent=None):
        if path not in self._folders:
            item = MeasurementItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setToolTip(str(path))
            item.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
            if parent is None:
                self.addTopLevelItem(item)
            else:
                parent.addChild(item)
            item.setExpanded(True)
            self._folders[path] = item
        return self._folders[path]

    def addItem(self, item):
        source = item.data(Qt.ItemDataRole.UserRole)
        anchor = source if isinstance(source, Path) else source.agilent
        root = next((root for root in self.roots if anchor.is_relative_to(root)), anchor.parent)
        parent = self._folder(root, root.name or str(root))
        directory = root
        for part in anchor.parent.relative_to(root).parts:
            directory /= part
            parent = self._folder(directory, part, parent)
        parent.addChild(item)
        self._items.append(item)

    def selectedItems(self):
        return [item for item in super().selectedItems() if item.data(Qt.ItemDataRole.UserRole) is not None]

    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]

    def row(self, item):
        return self._items.index(item)

    def takeItem(self, index):
        item = self._items.pop(index)
        parent = item.parent()
        parent.takeChild(parent.indexOfChild(item))
        while parent is not None and not parent.childCount():
            ancestor = parent.parent()
            self._folders = {path: node for path, node in self._folders.items() if node is not parent}
            if ancestor is None:
                self.takeTopLevelItem(self.indexOfTopLevelItem(parent))
            else:
                ancestor.takeChild(ancestor.indexOfChild(parent))
            parent = ancestor
        return item

    def setCurrentRow(self, index):
        item = self.item(index)
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.ClearAndSelect)
