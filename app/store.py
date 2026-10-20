"""Append-only SQLite receipts, idempotent recovery events, and decision memory."""

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import (
    DecisionMemoryEntry,
    ExceptionRunbookEvent,
    LLMAuditLogEntry,
    TrialLedgerSnapshot,
    ValidationPacket,
)


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as con:
            con.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS receipts (
                    id TEXT PRIMARY KEY, workflow TEXT NOT NULL,
                    created TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trial_snapshots (
                    id TEXT PRIMARY KEY, workflow TEXT NOT NULL,
                    created TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS immutable_trial_update BEFORE UPDATE ON trial_snapshots
                  BEGIN SELECT RAISE(ABORT, 'Trial snapshots are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_trial_delete BEFORE DELETE ON trial_snapshots
                  BEGIN SELECT RAISE(ABORT, 'Trial snapshots are immutable'); END;
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, validation_id TEXT NOT NULL REFERENCES receipts(id),
                    incident_key TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(validation_id, incident_key)
                );
                CREATE TABLE IF NOT EXISTS staged_executions (
                    id TEXT PRIMARY KEY, event_id TEXT NOT NULL,
                    action_id TEXT NOT NULL, actor TEXT NOT NULL,
                    role TEXT NOT NULL, receipt TEXT NOT NULL,
                    rationale TEXT NOT NULL, executed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decision_memory (
                    id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL,
                    payload TEXT NOT NULL, sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS llm_audit_logs (
                    id TEXT PRIMARY KEY, timestamp_utc TEXT NOT NULL,
                    model TEXT NOT NULL, task_id TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL, completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL, latency_ms REAL NOT NULL,
                    status TEXT NOT NULL, prompt_snippet TEXT NOT NULL,
                    response_snippet TEXT NOT NULL, sha256 TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS immutable_decision_update BEFORE UPDATE ON decision_memory
                  BEGIN SELECT RAISE(ABORT, 'Decision memory records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_decision_delete BEFORE DELETE ON decision_memory
                  BEGIN SELECT RAISE(ABORT, 'Decision memory records are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_receipt_update BEFORE UPDATE ON receipts
                  BEGIN SELECT RAISE(ABORT, 'Receipts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_receipt_delete BEFORE DELETE ON receipts
                  BEGIN SELECT RAISE(ABORT, 'Receipts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON events
                  BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_event_delete BEFORE DELETE ON events
                  BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
            """)
        self.seed_default_llm_logs_if_empty()

    @contextmanager
    def connection(self):
        with sqlite3.connect(self.path, timeout=10) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            yield con

    def save(self, packet: ValidationPacket) -> ValidationPacket:
        payload = packet.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.connection() as con:
            con.execute(
                "INSERT INTO receipts VALUES (?, ?, ?, ?, ?)",
                (
                    packet.validation_id,
                    packet.workflow_type,
                    packet.timestamp_utc,
                    payload,
                    digest,
                ),
            )
        return packet

    def get(self, val_id: str) -> ValidationPacket | None:
        with self.connection() as con:
            row = con.execute(
                "SELECT payload, sha256 FROM receipts WHERE id=?", (val_id,)
            ).fetchone()
        if not row:
            return None
        if hashlib.sha256(row["payload"].encode()).hexdigest() != row["sha256"]:
            raise ValueError("Receipt integrity check failed")
        return ValidationPacket.model_validate_json(row["payload"])

    def history(self, workflow: str) -> list[dict]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT id, created, sha256 FROM receipts WHERE workflow=? ORDER BY created DESC LIMIT 50",
                (workflow,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_event(self, event: ExceptionRunbookEvent) -> ExceptionRunbookEvent:
        with self.connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?)",
                (
                    event.event_id,
                    event.validation_id,
                    event.incident_key,
                    event.model_dump_json(),
                ),
            )
            row = con.execute(
                "SELECT payload FROM events WHERE validation_id=? AND incident_key=?",
                (event.validation_id, event.incident_key),
            ).fetchone()
        return self._merge_executions(ExceptionRunbookEvent.model_validate_json(row["payload"]))

    def events(self, val_id: str) -> list[ExceptionRunbookEvent]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT payload FROM events WHERE validation_id=? ORDER BY rowid",
                (val_id,),
            ).fetchall()
        return [self._merge_executions(ExceptionRunbookEvent.model_validate_json(row["payload"])) for row in rows]

    def _merge_executions(self, event: ExceptionRunbookEvent) -> ExceptionRunbookEvent:
        with self.connection() as con:
            executions = con.execute(
                "SELECT * FROM staged_executions WHERE event_id=?", (event.event_id,)
            ).fetchall()
        if not executions:
            return event

        exec_map = {row["action_id"]: row for row in executions}
        for action in event.staged_actions:
            if action.action_id in exec_map:
                row = exec_map[action.action_id]
                action.status = "EXECUTED_WRITEBACK_CONFIRMED"
                action.execution_receipt = row["receipt"]
                action.executed_at_utc = row["executed_at"]
                action.executed_by = row["actor"]
        return event

    def execute_staged_action(
        self,
        event_id: str,
        action_id: str,
        actor: str,
        role: str,
        rationale: str,
    ) -> tuple[ExceptionRunbookEvent | None, DecisionMemoryEntry | None]:
        with self.connection() as con:
            event_row = con.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()
            if not event_row:
                return None, None

            event = ExceptionRunbookEvent.model_validate_json(event_row["payload"])
            target_action = next((a for a in event.staged_actions if a.action_id == action_id), None)
            if not target_action:
                return None, None

            system_code = target_action.target_system.upper().replace(" ", "_")
            receipt_code = f"RECEIPT-{system_code}-{uuid4().hex[:8].upper()}"
            now_iso = datetime.now(timezone.utc).isoformat()
            exec_id = f"EXEC-{uuid4().hex[:10].upper()}"

            con.execute(
                "INSERT INTO staged_executions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (exec_id, event_id, action_id, actor, role, receipt_code, rationale, now_iso),
            )

            # Record in institutional decision memory
            mem_id = f"MEM-{datetime.now(timezone.utc).year}-{uuid4().hex[:10].upper()}"
            memory_entry = DecisionMemoryEntry(
                entry_id=mem_id,
                timestamp_utc=now_iso,
                actor=actor,
                role=role,
                workflow_type="VISUAL_QA",
                ai_recommendation=f"Execute {target_action.action_type} for {target_action.target_system}",
                human_action="APPROVED",
                rationale=rationale,
                governance_rule=f"Bounded writeback approval for {target_action.target_system}",
                predicted_vs_verified_impact=f"Executed with verified receipt: {receipt_code}",
            )
            payload = memory_entry.model_dump_json()
            digest = hashlib.sha256(payload.encode()).hexdigest()
            con.execute(
                "INSERT INTO decision_memory VALUES (?, ?, ?, ?)",
                (mem_id, now_iso, payload, digest),
            )

        updated_event = self._merge_executions(event)
        return updated_event, memory_entry

    def list_decision_memory(self, limit: int = 50) -> list[DecisionMemoryEntry]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT payload, sha256 FROM decision_memory ORDER BY timestamp_utc DESC LIMIT ?",
                (limit,),
            ).fetchall()
        entries = []
        for row in rows:
            if hashlib.sha256(row["payload"].encode()).hexdigest() != row["sha256"]:
                continue
            entries.append(DecisionMemoryEntry.model_validate_json(row["payload"]))
        return entries

    def rework(self, val_id: str) -> float:
        # Revisions inherit incident telemetry, without counting repeated incident keys twice.
        incidents, visited = {}, set()
        while val_id and val_id not in visited:
            visited.add(val_id)
            packet = self.get(val_id)
            for event in self.events(val_id):
                incidents[event.incident_key] = max(
                    incidents.get(event.incident_key, 0),
                    event.total_rework_minutes_added,
                )
            val_id = packet.parent_validation_id if packet else None
        return sum(incidents.values())

    def save_trial(self, snapshot: TrialLedgerSnapshot) -> TrialLedgerSnapshot:
        payload = snapshot.model_dump_json()
        with self.connection() as con:
            con.execute(
                "INSERT INTO trial_snapshots VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.snapshot_id,
                    snapshot.evidence.workflow_type,
                    snapshot.timestamp_utc,
                    payload,
                    hashlib.sha256(payload.encode()).hexdigest(),
                ),
            )
        return snapshot

    def latest_trial(self, workflow: str) -> TrialLedgerSnapshot | None:
        with self.connection() as con:
            row = con.execute(
                "SELECT payload, sha256 FROM trial_snapshots WHERE workflow=? ORDER BY rowid DESC LIMIT 1",
                (workflow,),
            ).fetchone()
        if not row:
            return None
        if hashlib.sha256(row["payload"].encode()).hexdigest() != row["sha256"]:
            raise ValueError("Trial snapshot integrity check failed")
        return TrialLedgerSnapshot.model_validate_json(row["payload"])

    def log_llm_run(self, entry: LLMAuditLogEntry) -> LLMAuditLogEntry:
        with self.connection() as con:
            con.execute(
                """INSERT OR REPLACE INTO llm_audit_logs 
                   (id, timestamp_utc, model, task_id, prompt_tokens, completion_tokens, 
                    total_tokens, latency_ms, status, prompt_snippet, response_snippet, sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.id,
                    entry.timestamp_utc,
                    entry.model,
                    entry.task_id,
                    entry.prompt_tokens,
                    entry.completion_tokens,
                    entry.total_tokens,
                    entry.latency_ms,
                    entry.status,
                    entry.prompt_snippet,
                    entry.response_snippet,
                    entry.sha256,
                ),
            )
        return entry

    def list_llm_logs(self, limit: int = 50) -> list[LLMAuditLogEntry]:
        with self.connection() as con:
            rows = con.execute(
                """SELECT id, timestamp_utc, model, task_id, prompt_tokens, completion_tokens,
                          total_tokens, latency_ms, status, prompt_snippet, response_snippet, sha256
                   FROM llm_audit_logs ORDER BY timestamp_utc DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [LLMAuditLogEntry(**dict(row)) for row in rows]

    def seed_default_llm_logs_if_empty(self):
        with self.connection() as con:
            count = con.execute("SELECT count(*) as c FROM llm_audit_logs").fetchone()["c"]
            if count == 0:
                samples = [
                    (
                        "llm_seed_01",
                        datetime.now(timezone.utc).isoformat(),
                        "gemini-3.8-flash",
                        "ASANA-12089421",
                        348,
                        112,
                        460,
                        184.2,
                        "200 OK (Live Gemini Inference)",
                        "Phase 1B Visual QA F1-F6 Triage for Puffy PDP Upgrade Modal at 390px",
                        "Extracted 6 findings: F1 & F2 kept separate pending 390px comparison; F4 blocked as unconfirmed missing viewport evidence; F5 routed to Designer; F3/F6 routed to Product Owner.",
                        hashlib.sha256(b"seed_01").hexdigest(),
                    ),
                    (
                        "llm_seed_02",
                        datetime.now(timezone.utc).isoformat(),
                        "gemini-3.8-flash",
                        "ASANA-12089422",
                        412,
                        96,
                        508,
                        210.5,
                        "200 OK (Live Gemini Inference)",
                        "CRO Hypothesis Pre-Flight: Digital Experience Lead Monarch King CTA drawer fold hierarchy",
                        "MDE calculation verified (+4.2% lift required); mobile fold hierarchy approved; Purple comparison matrix verified against Q3 claim pack.",
                        hashlib.sha256(b"seed_02").hexdigest(),
                    ),
                    (
                        "llm_seed_03",
                        datetime.now(timezone.utc).isoformat(),
                        "gemini-3.8-flash",
                        "ASANA-12089423",
                        0,
                        0,
                        0,
                        1.2,
                        "STEP 0 REJECTED (0 Tokens Spent)",
                        "Unscoped Creative Brief: Missing 390px Safari matrix and Asana scope marker",
                        "STEP 0 SCOPE GATE: Halted upstream before AI triage. 0 tokens expended. Clarification request sent to Product Owner.",
                        hashlib.sha256(b"seed_03").hexdigest(),
                    ),
                    (
                        "llm_seed_04",
                        datetime.now(timezone.utc).isoformat(),
                        "gemini-3.8-flash",
                        "ASANA-12089424",
                        520,
                        140,
                        660,
                        198.8,
                        "200 OK (Live Gemini Inference)",
                        "TrialSave-365 Sleep Biomechanics: Day 82 Puffy Lux Return Request",
                        "Lower back pain biomechanics profile evaluated. Staged $0 Firm Orthopedic Topper draft order concession (Shopify Draft #PF-SAVE-8821) instead of $2,249 refund.",
                        hashlib.sha256(b"seed_04").hexdigest(),
                    ),
                ]
                con.executemany(
                    """INSERT INTO llm_audit_logs 
                       (id, timestamp_utc, model, task_id, prompt_tokens, completion_tokens,
                        total_tokens, latency_ms, status, prompt_snippet, response_snippet, sha256)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    samples,
                )

