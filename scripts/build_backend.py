"""Build the FastAPI sidecar for Tauri. Run on Windows to produce the Windows x64 binary."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
backend = root / "backend"
output = root / "frontend" / "src-tauri" / "binaries"
output.mkdir(parents=True, exist_ok=True)
name = "agent-runtime-x86_64-pc-windows-msvc" if sys.platform == "win32" else "agent-runtime"
cmd = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--noconsole",
    "--hidden-import",
    "keyring.backends",
    "--hidden-import",
    "keyring.backends.Windows",
    "--hidden-import",
    "win32cred",
    "--name",
    name,
    "--distpath",
    str(output),
    "--workpath",
    str(backend / "build"),
    "--specpath",
    str(backend),
    str(backend / "run.py"),
]
subprocess.run(cmd, check=True, cwd=backend)
