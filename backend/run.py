"""Start the FastAPI sidecar safely in both console and windowed PyInstaller builds."""

from __future__ import annotations

import os
import sys

# PyInstaller's Windows --noconsole bootloader provides no standard streams. Uvicorn
# configures logging during import, so install harmless stream sinks before importing it.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import uvicorn

from app.core.config import settings
from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host=settings.agent_host, port=settings.agent_port, reload=False)
