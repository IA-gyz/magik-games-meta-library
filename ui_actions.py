"""Explicit semantic roles shared by all UI buttons; labels do not control styling."""

from PySide6.QtWidgets import QApplication, QPushButton

ROLES = ("sync", "metadata", "filter", "file", "settings", "launch", "danger")


def set_button_role(button, role):
    if role not in ROLES:
        raise ValueError("Unknown button role: " + str(role))
    button.setProperty("actionRole", role)
    manager = getattr(QApplication.instance(), "magik_appearance", None)
    if manager is not None:
        manager.style_button(button)
    return button


def action_button(text, role="settings", parent=None):
    return set_button_role(QPushButton(text, parent), role)
