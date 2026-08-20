"""Allow-listed desktop tools executed only through the permission engine.

The model may request one of these tools, but it never receives direct shell or OS access.
Each tool is explicitly registered with its required permission level.
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

import psutil

from app.models.schemas import PermissionLevel


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    permission: PermissionLevel
    description: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _require_windows(feature: str) -> None:
    if platform.system() != "Windows":
        raise RuntimeError(f"{feature} is only available on Windows")


def _refuse_system_root(path: Path) -> None:
    home = Path.home().resolve()
    if path == path.parent or path == home:
        raise ValueError("Refusing to operate on a system root or the entire home folder")


def _active_process(_: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded process list; no window content is read."""
    return {"processes": [proc.info for proc in psutil.process_iter(["pid", "name"])][:20]}


def _read_text_file(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _path(str(arguments["path"]))
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    if path.stat().st_size > 1_000_000:
        raise ValueError("Refusing to read files larger than 1 MB")
    return {"path": str(path), "content": path.read_text(encoding="utf-8", errors="replace")}


def _search_files(arguments: dict[str, Any]) -> dict[str, Any]:
    root = _path(str(arguments.get("root", Path.home())))
    pattern = str(arguments.get("pattern", "*"))
    if not root.is_dir():
        raise NotADirectoryError(f"Directory not found: {root}")
    matches = [str(item) for item in root.rglob(pattern) if item.is_file() or item.is_dir()][:50]
    return {
        "root": str(root),
        "pattern": pattern,
        "matches": matches,
        "truncated": len(matches) == 50,
    }


def _write_text_file(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _path(str(arguments["path"]))
    if path.exists() and not bool(arguments.get("overwrite", False)):
        raise FileExistsError(
            "Refusing to overwrite an existing file without explicit overwrite=true"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(arguments.get("content", "")), encoding="utf-8")
    return {"path": str(path), "written": True, "bytes": path.stat().st_size}


def _create_folder(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _path(str(arguments["path"]))
    path.mkdir(parents=True, exist_ok=True)
    return {"path": str(path), "created": True}


def _delete_path(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _path(str(arguments["path"]))
    _refuse_system_root(path)
    if not path.exists() and not path.is_symlink():
        raise FileNotFoundError(f"Path not found: {path}")
    if path.is_dir() and not path.is_symlink():
        if not bool(arguments.get("recursive", False)) and any(path.iterdir()):
            raise ValueError("Folder is not empty; explicit recursive=true is required")
        if bool(arguments.get("recursive", False)):
            shutil.rmtree(path)
        else:
            path.rmdir()
    else:
        path.unlink()
    return {"path": str(path), "deleted": True}


def _open_path(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _path(str(arguments["path"]))
    if not path.exists():
        raise FileNotFoundError(f"Path not found: {path}")
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif system == "Darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
    return {"opened": str(path)}


def _open_application(arguments: dict[str, Any]) -> dict[str, Any]:
    executable = str(arguments["executable"])
    if Path(executable).name != executable and not Path(executable).is_absolute():
        raise ValueError("Application must be a simple executable name or absolute path")
    subprocess.Popen([executable, *[str(x) for x in arguments.get("args", [])]])  # noqa: S603
    return {"started": executable}


def _list_applications(_: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded list of installed application names without starting anything."""
    _require_windows("Installed application listing")
    import winreg

    applications: set[str] = set()
    registry_roots = (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    )
    for hive, key_path in registry_roots:
        try:
            with winreg.OpenKey(hive, key_path) as root:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(root, index)
                        index += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, subkey_name) as subkey:
                            display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            if isinstance(display_name, str) and display_name.strip():
                                applications.add(display_name.strip())
                    except OSError:
                        continue
        except OSError:
            continue
    names = sorted(applications, key=str.casefold)
    return {"applications": names[:100], "truncated": len(names) > 100}


def _clipboard_read(_: dict[str, Any]) -> dict[str, Any]:
    import pyperclip

    return {"text": pyperclip.paste()[:10_000]}


def _clipboard_write(arguments: dict[str, Any]) -> dict[str, Any]:
    import pyperclip

    text = str(arguments["text"])
    if len(text) > 100_000:
        raise ValueError("Clipboard text is limited to 100,000 characters")
    pyperclip.copy(text)
    return {"written_characters": len(text)}


def _screenshot(arguments: dict[str, Any]) -> dict[str, Any]:
    """Capture locally and save a PNG; the image is never uploaded by this tool."""
    from PIL import ImageGrab

    requested = arguments.get("path")
    if requested:
        path = _path(str(requested))
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
    else:
        folder = Path.home() / "Pictures" / "Personal Assistant" / "Screenshots"
        path = folder / f"screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(all_screens=True)
    image.save(path, "PNG")
    return {"path": str(path), "captured": True, "size": list(image.size)}


def _set_volume(arguments: dict[str, Any]) -> dict[str, Any]:
    """Send bounded hardware-media key events to change the master volume on Windows."""
    _require_windows("Volume control")
    import ctypes

    action = str(arguments.get("action", "")).lower()
    virtual_keys = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}
    if action not in virtual_keys:
        raise ValueError("Volume action must be one of: up, down, mute")
    steps = 1 if action == "mute" else int(arguments.get("steps", 1))
    if not 1 <= steps <= 20:
        raise ValueError("Volume steps must be between 1 and 20")
    for _ in range(steps):
        ctypes.windll.user32.keybd_event(virtual_keys[action], 0, 0, 0)
        ctypes.windll.user32.keybd_event(virtual_keys[action], 0, 2, 0)
    return {"action": action, "steps": steps, "changed": True}


def _set_brightness(arguments: dict[str, Any]) -> dict[str, Any]:
    """Set integrated-display brightness through Windows WMI when the device supports it."""
    _require_windows("Brightness control")
    level = int(arguments["level"])
    if not 0 <= level <= 100:
        raise ValueError("Brightness level must be between 0 and 100")
    script = (
        "$methods = Get-CimInstance -Namespace root/WMI -ClassName "
        f"WmiMonitorBrightnessMethods; $methods | ForEach-Object {{ $_.WmiSetBrightness(1,{level}) }}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        shell=False,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )  # noqa: S603
    if completed.returncode != 0:
        raise RuntimeError(
            "Windows could not change brightness. This device may not expose integrated-display control."
        )
    return {"level": level, "changed": True}


def _open_settings(arguments: dict[str, Any]) -> dict[str, Any]:
    """Open a fixed Windows Settings area; arbitrary URI schemes are not accepted."""
    _require_windows("Windows Settings")
    page = str(arguments.get("page", "")).lower()
    pages = {
        "display": "ms-settings:display",
        "sound": "ms-settings:sound",
        "bluetooth": "ms-settings:bluetooth",
        "network": "ms-settings:network-status",
        "privacy": "ms-settings:privacy",
    }
    if page not in pages:
        raise ValueError(f"Settings page must be one of: {', '.join(pages)}")
    os.startfile(pages[page])  # type: ignore[attr-defined]  # noqa: S606
    return {"opened": page}


class _DuckDuckGoResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._capture = False
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or len(self.results) >= 5:
            return
        attributes = dict(attrs)
        if "result__a" not in (attributes.get("class") or ""):
            return
        self._capture = True
        self._href = attributes.get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._capture:
            return
        title = " ".join("".join(self._text).split())
        href = self._href
        if href.startswith("//duckduckgo.com/l/"):
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        if title and href:
            self.results.append({"title": title, "url": href})
        self._capture = False


def _web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    """Search the public web after confirmation; only the query leaves the computer."""
    query = str(arguments["query"]).strip()
    if not query:
        raise ValueError("Search query cannot be empty")
    if len(query) > 300:
        raise ValueError("Search query is limited to 300 characters")
    request = Request(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
        headers={"User-Agent": "PersonalAssistant/0.2 (local desktop assistant)"},
    )
    try:
        with urlopen(request, timeout=12) as response:  # noqa: S310
            content = response.read(1_000_000).decode("utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"Web search could not be completed: {exc}") from exc
    parser = _DuckDuckGoResultsParser()
    parser.feed(content)
    return {"query": query, "results": parser.results, "provider": "DuckDuckGo"}


def _terminal_command(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run only after the dangerous-tool toggle and explicit approval; never use shell=True."""
    command = arguments.get("command")
    if isinstance(command, str):
        command = shlex.split(command, posix=platform.system() != "Windows")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) for item in command)
    ):
        raise ValueError("Command must be a non-empty argument list")
    completed = subprocess.run(
        command, shell=False, capture_output=True, text=True, timeout=30, check=False
    )  # noqa: S603
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-5000:],
        "stderr": completed.stderr[-5000:],
    }


TOOLS: dict[str, RegisteredTool] = {
    "system.active_context": RegisteredTool(
        "system.active_context",
        PermissionLevel.SAFE,
        "Read a limited local process list without window content",
        _active_process,
    ),
    "application.list": RegisteredTool(
        "application.list",
        PermissionLevel.SAFE,
        "List up to 100 installed Windows applications",
        _list_applications,
    ),
    "filesystem.search": RegisteredTool(
        "filesystem.search", PermissionLevel.SAFE, "Search a selected folder", _search_files
    ),
    "filesystem.read_text": RegisteredTool(
        "filesystem.read_text", PermissionLevel.SAFE, "Read a text file up to 1 MB", _read_text_file
    ),
    "filesystem.write_text": RegisteredTool(
        "filesystem.write_text", PermissionLevel.CONFIRM, "Write a text file", _write_text_file
    ),
    "filesystem.create_file": RegisteredTool(
        "filesystem.create_file", PermissionLevel.CONFIRM, "Create a text file", _write_text_file
    ),
    "filesystem.create_folder": RegisteredTool(
        "filesystem.create_folder", PermissionLevel.CONFIRM, "Create a folder", _create_folder
    ),
    "filesystem.open": RegisteredTool(
        "filesystem.open", PermissionLevel.CONFIRM, "Open a file or folder with the OS", _open_path
    ),
    "filesystem.delete": RegisteredTool(
        "filesystem.delete", PermissionLevel.DANGEROUS, "Permanently delete a file or folder", _delete_path
    ),
    "application.open": RegisteredTool(
        "application.open", PermissionLevel.CONFIRM, "Start a user-named application", _open_application
    ),
    "clipboard.read": RegisteredTool(
        "clipboard.read", PermissionLevel.CONFIRM, "Read the clipboard", _clipboard_read
    ),
    "clipboard.write": RegisteredTool(
        "clipboard.write", PermissionLevel.CONFIRM, "Write to the clipboard", _clipboard_write
    ),
    "system.get_clipboard": RegisteredTool(
        "system.get_clipboard", PermissionLevel.CONFIRM, "Read the clipboard", _clipboard_read
    ),
    "system.set_clipboard": RegisteredTool(
        "system.set_clipboard", PermissionLevel.CONFIRM, "Write to the clipboard", _clipboard_write
    ),
    "system.screenshot": RegisteredTool(
        "system.screenshot", PermissionLevel.CONFIRM, "Capture and save a local PNG screenshot", _screenshot
    ),
    "system.volume": RegisteredTool(
        "system.volume", PermissionLevel.CONFIRM, "Change master volume using bounded media keys", _set_volume
    ),
    "system.brightness": RegisteredTool(
        "system.brightness", PermissionLevel.CONFIRM, "Set supported integrated-display brightness", _set_brightness
    ),
    "system.open_settings": RegisteredTool(
        "system.open_settings", PermissionLevel.CONFIRM, "Open a fixed Windows Settings page", _open_settings
    ),
    "web.search": RegisteredTool(
        "web.search", PermissionLevel.CONFIRM, "Search the public web; only the explicit query is sent", _web_search
    ),
    "terminal.run": RegisteredTool(
        "terminal.run", PermissionLevel.DANGEROUS, "Run a bounded command without a shell", _terminal_command
    ),
    "system.run_command": RegisteredTool(
        "system.run_command", PermissionLevel.DANGEROUS, "Run a bounded command without a shell", _terminal_command
    ),
}
