"""Standalone, offline message-workflow simulator.

This is a new portfolio implementation, not historical company code.
No network client is included. A caller supplies a fake transport callback.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Target:
    code: str
    opted_in: bool
    suppressed: bool = False


class Workflow:
    """Durable, idempotent outbox with explicit consent and an audit trail."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(database))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS targets (
                code TEXT PRIMARY KEY, opted_in INTEGER NOT NULL,
                suppressed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY, message TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                campaign TEXT NOT NULL REFERENCES campaigns(id),
                code TEXT NOT NULL REFERENCES targets(code),
                state TEXT NOT NULL DEFAULT 'queued',
                attempts INTEGER NOT NULL DEFAULT 0,
                due_at INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                PRIMARY KEY (campaign, code)
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign TEXT NOT NULL, code TEXT NOT NULL,
                event TEXT NOT NULL, recorded_at INTEGER NOT NULL
            );
        """)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_targets(self, targets: list[Target]) -> None:
        rows = []
        for t in targets:
            if not t.code.strip() or len(t.code) > 100:
                raise ValueError("target code must contain 1-100 characters")
            rows.append((t.code.strip(), int(t.opted_in), int(t.suppressed)))
        with self.conn:
            self.conn.executemany("""
                INSERT INTO targets(code, opted_in, suppressed) VALUES (?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    opted_in=excluded.opted_in, suppressed=excluded.suppressed
            """, rows)

    def define_campaign(self, campaign: str, message: str) -> None:
        if not campaign.strip() or not message.strip():
            raise ValueError("campaign and message must be nonempty")
        with self.conn:
            self.conn.execute(
                "INSERT INTO campaigns(id, message) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET message=excluded.message",
                (campaign, message),
            )

    def plan(self, campaign: str, now: int) -> int:
        if not self.conn.execute(
            "SELECT 1 FROM campaigns WHERE id=?", (campaign,)
        ).fetchone():
            raise ValueError("unknown campaign")
        with self.conn:
            self.conn.execute("""
                INSERT OR IGNORE INTO outbox(campaign, code, due_at)
                SELECT ?, code, ? FROM targets
                WHERE opted_in=1 AND suppressed=0
            """, (campaign, now))
            return self.conn.execute("SELECT changes()").fetchone()[0]

    def run(
        self,
        now: int,
        transport: Callable[[str, str], bool],
        *,
        limit: int = 100,
        max_attempts: int = 3,
    ) -> dict[str, int]:
        """Simulate due deliveries with bounded retries; never calls an API itself."""
        if limit < 1 or max_attempts < 1:
            raise ValueError("limit and max_attempts must be positive")
        due = self.conn.execute("""
            SELECT o.campaign, o.code, o.attempts, c.message,
                   t.opted_in, t.suppressed
            FROM outbox o
            JOIN campaigns c ON c.id=o.campaign
            JOIN targets t ON t.code=o.code
            WHERE o.state IN ('queued', 'retry') AND o.due_at<=?
            ORDER BY o.due_at, o.campaign, o.code LIMIT ?
        """, (now, limit)).fetchall()
        result: Counter[str] = Counter()
        for row in due:
            campaign, code = row["campaign"], row["code"]
            with self.conn:
                if not row["opted_in"] or row["suppressed"]:
                    state, event, attempt, error, when = (
                        "skipped", "consent_blocked", row["attempts"], None, now
                    )
                else:
                    attempt = row["attempts"] + 1
                    try:
                        succeeded = bool(transport(code, row["message"]))
                        error = None if succeeded else "simulated_failure"
                    except Exception as exc:  # transport failures are recorded, not leaked
                        succeeded = False
                        error = type(exc).__name__
                    if succeeded:
                        state, event, when = "delivered", "delivered", now
                    elif attempt >= max_attempts:
                        state, event, when = "dead", "retry_exhausted", now
                    else:
                        state, event = "retry", "retry_scheduled"
                        when = now + min(60 * (2 ** (attempt - 1)), 900)
                self.conn.execute("""
                    UPDATE outbox SET state=?, attempts=?, due_at=?, last_error=?
                    WHERE campaign=? AND code=?
                """, (state, attempt, when, error, campaign, code))
                self.conn.execute(
                    "INSERT INTO audit(campaign,code,event,recorded_at) "
                    "VALUES (?,?,?,?)", (campaign, code, event, now)
                )
                result[state] += 1
        return dict(result)

    def summary(self) -> dict[str, int]:
        return {
            row["state"]: row["total"]
            for row in self.conn.execute(
                "SELECT state, COUNT(*) total FROM outbox GROUP BY state"
            )
        }

    def audit(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT campaign,code,event,recorded_at FROM audit ORDER BY id"
        )]


def demonstration() -> None:
    flow = Workflow()
    flow.define_campaign("sample-campaign", "Example approved content")
    flow.upsert_targets([
        Target("fictional-01", True),
        Target("fictional-02", True),
        Target("fictional-03", False),
        Target("fictional-04", True, suppressed=True),
    ])
    flow.plan("sample-campaign", now=0)
    fail_once = {"fictional-02"}
    def fake_transport(code: str, _message: str) -> bool:
        if code in fail_once:
            fail_once.remove(code)
            return False
        return True
    flow.run(0, fake_transport)
    flow.run(60, fake_transport)
    print(json.dumps({
        "summary": flow.summary(), "audit": flow.audit(),
        "disclaimer": "No real messages were sent.",
    }, ensure_ascii=False, indent=2))
    flow.close()


if __name__ == "__main__":
    demonstration()
