"""Notifications natives OS (Toast Windows / notify-send Linux / osascript macOS).

Stdlib pure : on shell-out à PowerShell / notify-send / osascript selon l'OS.
Tout est best-effort : si ça plante, on logge et on continue.
"""
from __future__ import annotations

import platform
import subprocess
import sys


def _windows_toast(title: str, message: str) -> bool:
    """Toast Windows 10/11 via PowerShell + WinRT (sans dépendance externe)."""
    # Échappement minimal : on remplace " et ' par leur version sûre
    safe_title = title.replace("'", "''")
    safe_msg = message.replace("'", "''")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType=WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType=WindowsRuntime] | Out-Null;"
        "$tpl = '<toast><visual><binding template=\"ToastGeneric\"><text>'"
        f" + '{safe_title}' + '</text><text>' + '{safe_msg}' + '</text></binding></visual></toast>';"
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$xml.LoadXml($tpl);"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);"
        "$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PZ SaveSync');"
        "$notifier.Show($toast);"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _macos_toast(title: str, message: str) -> bool:
    """macOS notification via osascript."""
    safe_title = title.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe_msg}" with title "{safe_title}"'],
            capture_output=True, timeout=4,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _linux_toast(title: str, message: str) -> bool:
    """Linux : notify-send (libnotify)."""
    try:
        res = subprocess.run(
            ["notify-send", "-a", "PZ SaveSync", title, message],
            capture_output=True, timeout=4,
        )
        return res.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def notify(title: str, message: str) -> bool:
    """Affiche une notification native. Renvoie True si l'OS l'a acceptée."""
    if not title and not message:
        return False
    system = platform.system()
    try:
        if system == "Windows":
            return _windows_toast(title, message)
        if system == "Darwin":
            return _macos_toast(title, message)
        return _linux_toast(title, message)
    except Exception as e:
        print(f"[notify] erreur : {e}", file=sys.stderr)
        return False
