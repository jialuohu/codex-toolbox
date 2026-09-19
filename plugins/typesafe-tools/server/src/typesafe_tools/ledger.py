"""Private, durable reservations. Unsettled dispatches never receive automatic refunds."""

import os
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from .billing import MONTHLY_CAP, BillingBound
from .errors import EvaluationError


class Ledger:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "ledger.sqlite3"
        self.marker = root / "initialized"

    def _check(self, path: Path, directory: bool = False) -> None:
        info = path.lstat()
        correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if (not correct_type or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
                or (not directory and info.st_nlink != 1)):
            raise EvaluationError("accounting_unavailable")

    def _initialize(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check(self.root, directory=True)
        lock_path = self.root / "initialize.lock"
        if lock_path.exists() or lock_path.is_symlink():
            self._check(lock_path)
        with FileLock(str(lock_path), timeout=2, mode=0o600):
            # A crash between creation and completion leaves a mismatch and blocks reuse.
            if self.path.exists() != self.marker.exists():
                raise EvaluationError("accounting_unavailable")
            if self.path.exists():
                self._check(self.path)
                self._check(self.marker)
                return
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with sqlite3.connect(self.path) as db:
                db.executescript("""
                    PRAGMA synchronous=FULL;
                    CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), halted INTEGER NOT NULL);
                    INSERT INTO meta VALUES(1, 0);
                    CREATE TABLE reservations (
                      id TEXT PRIMARY KEY, month TEXT NOT NULL, submitted TEXT NOT NULL,
                      reserved INTEGER NOT NULL CHECK(reserved>0), rate INTEGER NOT NULL,
                      max_tokens INTEGER NOT NULL, evidence TEXT NOT NULL,
                      charged INTEGER, input_tokens INTEGER, output_tokens INTEGER,
                      classification TEXT, invocation TEXT, question_count INTEGER,
                      payload_bytes INTEGER,
                      CHECK(charged IS NULL OR charged>=0));
                    PRAGMA user_version=2;
                """)
            fd = os.open(self.marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, b"typesafe-ledger-v2\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    @contextmanager
    def _database(self, initialize: bool = False, readonly: bool = False):
        try:
            if initialize:
                self._initialize()
            self._check(self.root, directory=True)
            self._check(self.path)
            self._check(self.marker)
            mode = "ro" if readonly else "rw"
            db = sqlite3.connect(self.path.as_uri() + "?mode=" + mode, uri=True, timeout=2)
            try:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
                if (db.execute("PRAGMA user_version").fetchone()[0] != 2
                        or db.execute("PRAGMA quick_check").fetchone()[0] != "ok"
                        or db.execute("SELECT halted FROM meta WHERE id=1").fetchone() != (0,)):
                    raise EvaluationError("accounting_unavailable")
                inconsistent = db.execute("""
                    SELECT 1 FROM reservations WHERE
                      rate<=0 OR max_tokens<=0 OR reserved!=rate*max_tokens OR reserved>?
                      OR (charged IS NULL AND
                          (input_tokens IS NOT NULL OR output_tokens IS NOT NULL))
                      OR (charged IS NOT NULL AND
                          (input_tokens IS NULL OR output_tokens IS NULL OR input_tokens<0
                           OR output_tokens<0 OR input_tokens>max_tokens
                           OR charged!=input_tokens*rate))
                    LIMIT 1
                """, (MONTHLY_CAP,)).fetchone()
                if inconsistent:
                    raise EvaluationError("accounting_unavailable")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()
        except EvaluationError:
            raise
        except Exception as exc:
            raise EvaluationError("accounting_unavailable") from exc

    def reserve(self, bound: BillingBound, limit: int, now: datetime,
                metadata: dict | None = None) -> str:
        if not bound.valid(now) or not 0 < limit <= MONTHLY_CAP:
            raise EvaluationError("hard_cap_unverified")
        audit = metadata or {}
        fields = {"classification", "invocation", "question_count", "payload_bytes"}
        if audit and (set(audit) != fields
                      or audit["classification"] not in {"public", "synthetic"}
                      or audit["invocation"] not in {"explicit", "automatic"}
                      or type(audit["question_count"]) is not int
                      or not 1 <= audit["question_count"] <= 16
                      or type(audit["payload_bytes"]) is not int
                      or not 1 <= audit["payload_bytes"] <= 24 * 1024):
            raise EvaluationError("invalid_request")
        month = now.astimezone(UTC).strftime("%Y-%m")
        with self._database(initialize=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='uncapped_requests'").fetchone():
                if db.execute("SELECT 1 FROM uncapped_requests WHERE month=? LIMIT 1",
                              (month,)).fetchone():
                    # Unpriced usage cannot become a claimed hard cap by changing configuration.
                    raise EvaluationError("accounting_unavailable")
            used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0)"
                " FROM reservations WHERE month=?",
                (month,),
            ).fetchone()[0]
            if used + bound.reservation > limit:
                raise EvaluationError("budget_exhausted")
            identifier = uuid.uuid4().hex
            db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,?,?,?,?)",
                       (identifier, month, now.astimezone(UTC).isoformat(), bound.reservation,
                        bound.nanousd_per_input_token, bound.max_input_tokens, bound.evidence_id,
                        audit.get("classification"), audit.get("invocation"),
                        audit.get("question_count"), audit.get("payload_bytes")))
        return identifier

    def settle(self, identifier: str, input_tokens: int, output_tokens: int) -> int:
        exceeded = False
        with self._database() as db:
            row = db.execute("SELECT reserved,rate,max_tokens,charged FROM reservations WHERE id=?",
                             (identifier,)).fetchone()
            if (row is None or row[3] is not None or type(input_tokens) is not int
                    or type(output_tokens) is not int or min(input_tokens, output_tokens) < 0):
                db.execute("UPDATE meta SET halted=1 WHERE id=1")
                exceeded = True
                charged = 0
            else:
                reserved, rate, maximum, _ = row
                charged = input_tokens * rate
                # SQLite integers are bounded; retain reservation and halt on impossible usage.
                if charged > 2**63 - 1 or input_tokens > 2**63 - 1 or output_tokens > 2**63 - 1:
                    db.execute("UPDATE meta SET halted=1 WHERE id=1")
                    exceeded = True
                else:
                    db.execute("UPDATE reservations SET charged=?, input_tokens=?, output_tokens=?"
                               " WHERE id=?", (charged, input_tokens, output_tokens, identifier))
                    if input_tokens > maximum or charged > reserved:
                        db.execute("UPDATE meta SET halted=1 WHERE id=1")
                        exceeded = True
        if exceeded:
            raise EvaluationError("billing_bound_exceeded")
        return charged

    def status(self, now: datetime) -> dict:
        if not self.root.exists() and not self.root.is_symlink():
            return {"initialized": False, "used_nanousd": 0, "unsettled_reservations": 0}
        # Even empty/missing ledgers after a prior initialization fail closed.
        with self._database(readonly=True) as db:
            month = now.astimezone(UTC).strftime("%Y-%m")
            used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0)"
                " FROM reservations WHERE month=?",
                (month,),
            ).fetchone()[0]
            count = db.execute(
                "SELECT COUNT(*) FROM reservations WHERE charged IS NULL"
            ).fetchone()[0]
            unpriced = 0
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='uncapped_requests'").fetchone():
                unpriced = db.execute("SELECT COUNT(*) FROM uncapped_requests WHERE month=?",
                                      (month,)).fetchone()[0]
        return {"initialized": True, "used_nanousd": used, "unsettled_reservations": count,
                "unpriced_requests_this_month": unpriced}

    def start_unlimited(self, now: datetime, metadata: dict) -> str:
        """Durably record dispatch without reserving or estimating any monetary cost."""
        identifier = uuid.uuid4().hex
        with self._database(initialize=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS uncapped_requests (
                id TEXT PRIMARY KEY, month TEXT NOT NULL, submitted TEXT NOT NULL,
                classification TEXT NOT NULL, invocation TEXT NOT NULL,
                question_count INTEGER NOT NULL, payload_bytes INTEGER NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER,
                CHECK(input_tokens IS NULL OR input_tokens>=0),
                CHECK(output_tokens IS NULL OR output_tokens>=0))""")
            db.execute("INSERT INTO uncapped_requests VALUES(?,?,?,?,?,?,?,NULL,NULL)",
                       (identifier, now.astimezone(UTC).strftime("%Y-%m"),
                        now.astimezone(UTC).isoformat(), metadata["classification"],
                        metadata["invocation"], metadata["question_count"],
                        metadata["payload_bytes"]))
        return identifier

    def finish_unlimited(self, identifier: str, input_tokens: int, output_tokens: int) -> None:
        invalid = False
        with self._database() as db:
            if (any(type(value) is not int or not 0 <= value <= 2**63 - 1
                    for value in (input_tokens, output_tokens))):
                invalid = True
            else:
                result = db.execute("UPDATE uncapped_requests SET input_tokens=?,output_tokens=?"
                                    " WHERE id=? AND input_tokens IS NULL"
                                    " AND output_tokens IS NULL",
                                    (input_tokens, output_tokens, identifier))
                invalid = result.rowcount != 1
            if invalid:
                db.execute("UPDATE meta SET halted=1 WHERE id=1")
        if invalid:
            raise EvaluationError("accounting_unavailable")

    def unlimited_status(self, now: datetime) -> dict:
        legacy = self.status(now)
        result = {"initialized": legacy["initialized"], "requests_this_month": 0,
                  "input_tokens": 0, "output_tokens": 0, "unresolved_requests": 0,
                  "charged_nanousd": None, "legacy_capped_accounting": legacy}
        if not legacy["initialized"]:
            return result
        with self._database(readonly=True) as db:
            table = db.execute("SELECT 1 FROM sqlite_master WHERE name='uncapped_requests'")
            if not table.fetchone():
                return result
            # Sum in Python to avoid integer overflow in SQLite's SUM aggregate.
            rows = db.execute("SELECT input_tokens,output_tokens FROM uncapped_requests"
                              " WHERE month=?",
                              (now.astimezone(UTC).strftime("%Y-%m"),)).fetchall()
            result.update(requests_this_month=len(rows),
                          input_tokens=sum(row[0] or 0 for row in rows),
                          output_tokens=sum(row[1] or 0 for row in rows))
            result["unresolved_requests"] = db.execute(
                "SELECT COUNT(*) FROM uncapped_requests WHERE input_tokens IS NULL").fetchone()[0]
        return result
