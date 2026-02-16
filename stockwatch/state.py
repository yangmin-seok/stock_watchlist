from __future__ import annotations

import sqlite3
from datetime import datetime


class AlertStateStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY (alert_date, ticker, rule_id)
                )
                """
            )

    def was_sent(self, alert_date: str, ticker: str, rule_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM alerts WHERE alert_date=? AND ticker=? AND rule_id=?",
                (alert_date, ticker, rule_id),
            ).fetchone()
        return row is not None

    def mark_sent(self, alert_date: str, ticker: str, rule_id: str) -> None:
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO alerts (alert_date, ticker, rule_id, sent_at)
                VALUES (?, ?, ?, ?)
                """,
                (alert_date, ticker, rule_id, now),
            )
