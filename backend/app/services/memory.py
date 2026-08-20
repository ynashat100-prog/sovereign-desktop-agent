"""Opt-in local long-term memory backed by LanceDB, never storing screenshots automatically."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class MemoryService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.enabled = True
        self._db = None

    def _connect(self):
        if not self.enabled:
            return None
        if self._db is not None:
            return self._db
        try:
            import lancedb

            self.path.mkdir(parents=True, exist_ok=True)
            self._db = lancedb.connect(str(self.path))
            return self._db
        except Exception:
            # Memory is an optional privacy feature; callers should keep working without it.
            return None

    def remember(self, session_id: str, text: str) -> bool:
        db = self._connect()
        if not db:
            return False
        try:
            row = {
                "session_id": session_id,
                "text": text[:4000],
                "created_at": datetime.now(UTC).isoformat(),
            }
            if "episodic" in db.table_names():
                db.open_table("episodic").add([row])
            else:
                db.create_table("episodic", [row])
            return True
        except Exception:
            return False

    def clear_all(self) -> bool:
        db = self._connect()
        if not db:
            return False
        try:
            for table in db.table_names():
                db.drop_table(table)
            return True
        except Exception:
            return False
