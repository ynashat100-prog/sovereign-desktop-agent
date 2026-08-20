"""Allow-listed desktop tools. The model can request them but never execute OS commands directly."""

from __future__ import annotations

import os
import platform
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def _create_file(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _path(str(arguments["path"]))
    if path.exists() and not bool(arguments.get("overwrite", False)):
        raise FileExistsError(
            "Refusing to overwrite an existing file without explicit overwrite=true"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(arguments.get("content", "")), encoding="utf-8")
    return {"path": str(path), "created": True, "bytes": path.stat().st_size}


def _create_folder(arguments: dict[str, Any]) -> dict[str, Any]:
    path = _path(str(arguments["path"]))
    path.mkdir(parents=True, exist_ok=True)
    return {"path": str(path), "created": True}


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


def _clipboard_read(_: dict[str, Any]) -> dict[str, Any]:
    import pyperclip

    return {"text": pyperclip.paste()[:10_000]}


def _clipboard_write(arguments: dict[str, Any]) -> dict[str, Any]:
    import pyperclip

    text = str(arguments["text"])
    pyperclip.copy(text)
    return {"written_characters": len(text)}


def _terminal_command(arguments: dict[str, Any]) -> dict[str, Any]:
    """Called only after the dangerous-tool toggle and an explicit approval; never uses shell=True."""
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
        "Read limited local process context",
        _active_process,
    ),
    "filesystem.search": RegisteredTool(
        "filesystem.search", PermissionLevel.SAFE, "Search a selected folder", _search_files
    ),
    "filesystem.read_text": RegisteredTool(
        "filesystem.read_text", PermissionLevel.SAFE, "Read a text file up to 1 MB", _read_text_file
    ),
    "filesystem.create_file": RegisteredTool(
        "filesystem.create_file", PermissionLevel.CONFIRM, "Create a text file", _create_file
    ),
    "filesystem.create_folder": RegisteredTool(
        "filesystem.create_folder", PermissionLevel.CONFIRM, "Create a folder", _create_folder
    ),
    "filesystem.open": RegisteredTool(
        "filesystem.open", PermissionLevel.CONFIRM, "Open a file or folder with the OS", _open_path
    ),
    "application.open": RegisteredTool(
        "application.open",
        PermissionLevel.CONFIRM,
        "Start a user-named application",
        _open_application,
    ),
    "clipboard.read": RegisteredTool(
        "clipboard.read", PermissionLevel.CONFIRM, "Read the clipboard", _clipboard_read
    ),
    "clipboard.write": RegisteredTool(
        "clipboard.write", PermissionLevel.CONFIRM, "Write to the clipboard", _clipboard_write
    ),
    "terminal.run": RegisteredTool(
        "terminal.run",
        PermissionLevel.DANGEROUS,
        "Run a bounded command without a shell",
        _terminal_command,
    ),
}
