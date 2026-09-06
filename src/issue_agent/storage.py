import hmac
import json
import secrets
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from issue_agent.models import ApprovalProof
from issue_agent.security import DomainError, canonical, digest, fingerprint, redact


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, session TEXT NOT NULL, tool TEXT NOT NULL,
                    arguments TEXT NOT NULL, fingerprint TEXT NOT NULL, impact TEXT NOT NULL,
                    status TEXT NOT NULL, expires REAL NOT NULL, token_hash TEXT,
                    result TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS executions (
                    fingerprint TEXT PRIMARY KEY, action_id TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL,
                    event TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS budgets (
                    id TEXT PRIMARY KEY, used INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session TEXT NOT NULL, result TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _audit(db: sqlite3.Connection, session: str, event: str, detail: Any) -> None:
        db.execute(
            "INSERT INTO audit(session,event,detail,created) VALUES(?,?,?,?)",
            (session, event, canonical(redact(detail)), time.time()),
        )

    def audit(self, session: str, event: str, detail: Any) -> None:
        with self.connection() as db:
            self._audit(db, session, event, detail)

    def events(self, session: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,event,detail,created FROM audit WHERE session=? "
                "ORDER BY id DESC LIMIT 100",
                (session,),
            ).fetchall()
        return [dict(row) | {"detail": json.loads(row["detail"])} for row in rows]

    def session(self, cookie: str | None) -> tuple[str, str]:
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE id=? AND expires>?",
                (digest(cookie or ""), time.time()),
            ).fetchone()
            if row and cookie:
                return cookie, str(row["csrf"])
            cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)", (digest(cookie), csrf, time.time() + 86400)
            )
            return cookie, csrf

    def require_session(self, cookie: str | None, csrf: str | None = None) -> str:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE id=? AND expires>?",
                (digest(cookie or ""), time.time()),
            ).fetchone()
        if row is None or (csrf is not None and not hmac.compare_digest(row["csrf"], csrf)):
            raise DomainError("INVALID_SESSION")
        return str(row["id"])

    @staticmethod
    def public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tool": row["tool"],
            "arguments": json.loads(row["arguments"]),
            "fingerprint": row["fingerprint"],
            "impact": row["impact"],
            "status": row["status"],
            "expires": row["expires"],
            "permission": "REQUIRE_CONFIRM",
            "result": json.loads(row["result"] or "null"),
        }

    def pending(
        self, session: str, tool: str, arguments: dict[str, Any], impact: str, ttl: int = 300
    ) -> dict[str, Any]:
        fp, now = fingerprint(tool, arguments), time.time()
        with self.transaction() as db:
            existing = db.execute(
                "SELECT * FROM actions WHERE session=? AND fingerprint=? "
                "AND status IN ('PENDING','APPROVED','EXECUTING','SUCCEEDED',"
                "'UNKNOWN') AND expires>? ORDER BY created DESC LIMIT 1",
                (session, fp, now),
            ).fetchone()
            if existing:
                return self.public(existing)
            action_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    action_id,
                    session,
                    tool,
                    canonical(arguments),
                    fp,
                    impact,
                    "PENDING",
                    now + ttl,
                    None,
                    None,
                    now,
                ),
            )
            self._audit(db, session, "PROPOSED", {"action_id": action_id, "tool": tool, "hash": fp})
            row = db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
            return self.public(row)

    def get_action(self, session: str, action_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM actions WHERE id=? AND session=?", (action_id, session)
            ).fetchone()
        if not row:
            raise DomainError("ACTION_NOT_FOUND")
        result = self.public(row)
        if result["status"] in {"PENDING", "APPROVED"} and result["expires"] <= time.time():
            result["status"] = "EXPIRED"
        return result

    def list_actions(self, session: str) -> list[dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id FROM actions WHERE session=? ORDER BY created DESC LIMIT 50", (session,)
            ).fetchall()
        return [self.get_action(session, row[0]) for row in rows]

    def decide(self, session: str, action_id: str, approve: bool) -> ApprovalProof | None:
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM actions WHERE id=? AND session=?", (action_id, session)
            ).fetchone()
            if not row:
                raise DomainError("ACTION_NOT_FOUND")
            if row["expires"] <= time.time():
                self._audit(db, session, "APPROVAL_EXPIRED", {"action_id": action_id})
                error = "APPROVAL_EXPIRED"
            elif row["status"] != "PENDING":
                self._audit(db, session, "DUPLICATE_DECISION", {"action_id": action_id})
                error = "ACTION_ALREADY_DECIDED"
            else:
                token = secrets.token_urlsafe(32) if approve else ""
                status = "APPROVED" if approve else "REJECTED"
                db.execute(
                    "UPDATE actions SET status=?,token_hash=? WHERE id=?",
                    (status, digest(token) if approve else None, action_id),
                )
                self._audit(db, session, status, {"action_id": action_id})
                return (
                    ApprovalProof(action_id=action_id, session_id=session, token=token)
                    if approve
                    else None
                )
        raise DomainError(error)

    def claim(self, tool: str, arguments: dict[str, Any], proof: ApprovalProof | None) -> str:
        if proof is None:
            raise DomainError("REQUIRE_CONFIRM")
        fp = fingerprint(tool, arguments)
        with self.transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE id=?", (proof.action_id,)).fetchone()
            if not row or row["session"] != proof.session_id:
                error = "BLOCK_APPROVAL_BINDING"
            elif row["status"] != "APPROVED":
                error = "APPROVAL_ALREADY_USED"
            elif not hmac.compare_digest(row["token_hash"] or "", digest(proof.token)):
                error = "BLOCK_APPROVAL_BINDING"
            elif (
                row["tool"] != tool
                or row["fingerprint"] != fp
                or fingerprint(tool, json.loads(row["arguments"])) != fp
            ):
                db.execute(
                    "UPDATE actions SET status='INVALIDATED',token_hash=NULL WHERE id=?",
                    (proof.action_id,),
                )
                error = "BLOCK_APPROVAL_BINDING"
            elif row["expires"] <= time.time():
                error = "APPROVAL_EXPIRED"
            else:
                duplicate = db.execute(
                    "SELECT * FROM executions WHERE fingerprint=?", (fp,)
                ).fetchone()
                if duplicate:
                    db.execute(
                        "UPDATE actions SET status='DUPLICATE',token_hash=NULL WHERE id=?",
                        (proof.action_id,),
                    )
                    error = "DUPLICATE_SUPPRESSED"
                else:
                    db.execute(
                        "INSERT INTO executions VALUES(?,?,?)", (fp, proof.action_id, "EXECUTING")
                    )
                    db.execute(
                        "UPDATE actions SET status='EXECUTING',token_hash=NULL WHERE id=?",
                        (proof.action_id,),
                    )
                    self._audit(
                        db,
                        proof.session_id,
                        "EXECUTION_CLAIMED",
                        {"action_id": proof.action_id, "hash": fp},
                    )
                    return proof.action_id
            self._audit(db, proof.session_id, error, {"action_id": proof.action_id})
        raise DomainError(error)

    def finish(self, action_id: str, status: str, result: dict[str, Any]) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE actions SET status=?,result=? WHERE id=? AND status='EXECUTING'",
                (status, canonical(redact(result)), action_id),
            )
            db.execute("UPDATE executions SET status=? WHERE action_id=?", (status, action_id))
            row = db.execute("SELECT session FROM actions WHERE id=?", (action_id,)).fetchone()
            self._audit(db, row["session"], status, {"action_id": action_id, "result": result})

    def consume(self, run_id: str, limit: int) -> int:
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO budgets VALUES(?,0)", (run_id,))
            used = int(db.execute("SELECT used FROM budgets WHERE id=?", (run_id,)).fetchone()[0])
            if used >= limit:
                raise DomainError("REQUEST_BUDGET_EXHAUSTED")
            db.execute("UPDATE budgets SET used=used+1 WHERE id=?", (run_id,))
            return used + 1

    def save_run(self, session: str, run_id: str, result: dict[str, Any]) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES(?,?,?)",
                (run_id, session, canonical(redact(result))),
            )

    def get_run(self, session: str, run_id: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                "SELECT result FROM runs WHERE id=? AND session=?", (run_id, session)
            ).fetchone()
        if row is None:
            raise DomainError("RUN_NOT_FOUND")
        return dict(json.loads(row[0]))
