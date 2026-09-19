"""Small SQLite state store for replay progress, signals, and report snapshots."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from src.models import MarketSignal


class SignalStore:
    def __init__(self, path: str = "data/market_signal.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS processed_contexts (
                    context_key TEXT PRIMARY KEY,
                    message_ids TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context_key TEXT NOT NULL,
                    source_msg_ids TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context_key TEXT NOT NULL,
                    error TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def has_context(self, context_key: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM processed_contexts WHERE context_key = ?", (context_key,)
            ).fetchone() is not None

    def replace_context_signals(
        self, context_key: str, message_ids: Iterable[str], signals: List[MarketSignal]
    ) -> None:
        message_ids = set(message_ids)
        with self._connect() as connection:
            existing = connection.execute("SELECT id, source_msg_ids FROM signals").fetchall()
            delete_ids = [
                row["id"]
                for row in existing
                if message_ids.intersection(json.loads(row["source_msg_ids"]))
            ]
            if delete_ids:
                connection.executemany("DELETE FROM signals WHERE id = ?", [(item,) for item in delete_ids])
            connection.execute("DELETE FROM processed_contexts WHERE context_key = ?", (context_key,))
            connection.execute(
                "INSERT OR REPLACE INTO processed_contexts(context_key, message_ids, processed_at) VALUES (?, ?, ?)",
                (context_key, json.dumps(sorted(message_ids)), datetime.now(timezone.utc).isoformat()),
            )
            for signal in signals:
                connection.execute(
                    "INSERT INTO signals(context_key, source_msg_ids, payload, created_at) VALUES (?, ?, ?, ?)",
                    (
                        context_key,
                        json.dumps(signal.source_msg_ids),
                        signal.model_dump_json(),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

    def record_failure(self, context_key: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO failures(context_key, error, created_at) VALUES (?, ?, ?)",
                (context_key, error, datetime.now(timezone.utc).isoformat()),
            )

    def load_signals(self) -> List[MarketSignal]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM signals ORDER BY id").fetchall()
        return [MarketSignal.model_validate(json.loads(row["payload"])) for row in rows]

    def load_failures(self, limit: int = 20) -> List[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT context_key, error FROM failures ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [f"{row['context_key']}: {row['error']}" for row in rows]

    def reset(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM processed_contexts")
            connection.execute("DELETE FROM signals")
            connection.execute("DELETE FROM failures")
