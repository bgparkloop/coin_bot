from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import StrategyConfig


class StateStore:
    def __init__(self, config: StrategyConfig):
        self.db_path = Path(config.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS symbol_state (
                    symbol TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    max_leverage REAL NOT NULL DEFAULT 5,
                    hedge_ratio REAL NOT NULL DEFAULT 0.25,
                    regime TEXT NOT NULL DEFAULT 'unknown',
                    last_signal_at INTEGER NOT NULL DEFAULT 0,
                    last_action TEXT,
                    main_side TEXT NOT NULL DEFAULT 'flat',
                    main_qty REAL NOT NULL DEFAULT 0,
                    main_avg REAL NOT NULL DEFAULT 0,
                    main_entries INTEGER NOT NULL DEFAULT 0,
                    main_last_entry_at INTEGER NOT NULL DEFAULT 0,
                    hedge_side TEXT NOT NULL DEFAULT 'none',
                    hedge_qty REAL NOT NULL DEFAULT 0,
                    hedge_avg REAL NOT NULL DEFAULT 0,
                    hedge_ratio_live REAL NOT NULL DEFAULT 0,
                    estimated_leverage REAL NOT NULL DEFAULT 0,
                    unrealized_pnl REAL NOT NULL DEFAULT 0,
                    meta_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dedupe_log (
                    dedupe_key TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL
                );
                """
            )
            conn.commit()

    def bootstrap_symbols(self, config: StrategyConfig) -> None:
        with self.connect() as conn:
            for symbol, symbol_config in config.symbols.items():
                conn.execute(
                    """
                    INSERT INTO symbol_state(symbol, enabled, max_leverage, hedge_ratio)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        max_leverage=excluded.max_leverage
                    """,
                    (
                        symbol,
                        1 if symbol_config.enabled else 0,
                        symbol_config.max_leverage,
                        symbol_config.default_hedge_ratio,
                    ),
                )
            conn.execute(
                """
                INSERT INTO app_state(key, value)
                VALUES ('trading_enabled', '1')
                ON CONFLICT(key) DO NOTHING
                """
            )
            conn.commit()

    def is_duplicate(self, dedupe_key: str, debounce_seconds: int) -> bool:
        cutoff = int(time.time()) - debounce_seconds
        with self.connect() as conn:
            conn.execute("DELETE FROM dedupe_log WHERE created_at < ?", (cutoff,))
            row = conn.execute(
                "SELECT dedupe_key FROM dedupe_log WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if row:
                conn.commit()
                return True
            conn.execute(
                "INSERT INTO dedupe_log(dedupe_key, created_at) VALUES (?, ?)",
                (dedupe_key, int(time.time())),
            )
            conn.commit()
            return False

    def get_symbol_state(self, symbol: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM symbol_state WHERE symbol = ?",
                (symbol,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown symbol: {symbol}")
            state = dict(row)
            state["meta"] = json.loads(state.pop("meta_json", "{}"))
            return state

    def update_symbol_state(self, symbol: str, **changes: Any) -> None:
        if not changes:
            return
        if "meta" in changes:
            changes["meta_json"] = json.dumps(changes.pop("meta"), ensure_ascii=False)
        columns = ", ".join(f"{key} = ?" for key in changes)
        params = list(changes.values()) + [symbol]
        with self.connect() as conn:
            conn.execute(f"UPDATE symbol_state SET {columns} WHERE symbol = ?", params)
            conn.commit()

    def log_event(self, symbol: str, event_type: str, message: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO event_log(symbol, event_type, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (symbol, event_type, message, json.dumps(payload, ensure_ascii=False), int(time.time())),
            )
            conn.commit()

    def recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM event_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_trading_enabled(self) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key = 'trading_enabled'"
            ).fetchone()
            return row is None or row["value"] == "1"

    def set_trading_enabled(self, enabled: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state(key, value) VALUES ('trading_enabled', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("1" if enabled else "0",),
            )
            conn.commit()

    def all_symbol_states(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM symbol_state ORDER BY symbol").fetchall()
            states = []
            for row in rows:
                item = dict(row)
                item["meta"] = json.loads(item.pop("meta_json", "{}"))
                states.append(item)
            return states

