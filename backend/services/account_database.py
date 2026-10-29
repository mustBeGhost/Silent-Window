"""Pooled MySQL storage with explicit schema setup; SQLite supports isolated tests.

All SQL passed to execute is application-owned. User values always remain bound
parameters. The small row/result adapter keeps the existing repositories portable.
"""
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import (CheckConstraint, Column, Float, ForeignKey, Index, Integer,
                        MetaData, String, Table, Text, create_engine, event, text)
from sqlalchemy.engine import URL, make_url

SCHEMA_VERSION = 7
metadata = MetaData()
table_options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}


def table(name, *columns):
    return Table(name, metadata, *columns, **table_options)


users = table("users", Column("id", Integer, primary_key=True),
    Column("username", String(32), nullable=False, unique=True),
    Column("display_name", String(60), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(16), nullable=False), Column("active", Integer, nullable=False, server_default="1"),
    Column("preferred_model", String(16), nullable=False, server_default="original"),
    Column("page_size", Integer, nullable=False, server_default="25"),
    Column("replay_step", Integer, nullable=False, server_default="60"), Column("created_at", Float(precision=53), nullable=False),
    CheckConstraint("role IN ('admin','doctor','nurse','coordinator','researcher')", name="ck_users_role"),
    CheckConstraint("active IN (0,1)", name="ck_users_active"))
sessions = table("sessions", Column("token_hash", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("created_at", Float(precision=53), nullable=False), Column("last_seen", Float(precision=53), nullable=False),
    Column("expires_at", Float(precision=53), nullable=False))
attempts = table("attempts", Column("bucket", String(64), primary_key=True),
    Column("started_at", Float(precision=53), nullable=False), Column("count", Integer, nullable=False))
account_events = table("account_events", Column("id", Integer, primary_key=True),
    Column("actor_id", Integer, ForeignKey("users.id")), Column("target_id", Integer, ForeignKey("users.id")),
    Column("action", String(32), nullable=False), Column("created_at", Float(precision=53), nullable=False))
assignments = table("assignments", Column("patient_id", String(32), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("assigned_by", Integer, ForeignKey("users.id"), nullable=False), Column("created_at", Float(precision=53), nullable=False))
patient_events = table("patient_events", Column("id", Integer, primary_key=True),
    Column("patient_id", String(32), nullable=False), Column("model_profile", String(16), nullable=False),
    Column("checkpoint", String(8), nullable=False), Column("event_type", String(16), nullable=False), Column("content", Text, nullable=False),
    Column("actor_id", Integer, ForeignKey("users.id"), nullable=False), Column("actor_role", String(16), nullable=False),
    Column("risk_score", Float(precision=53), nullable=False), Column("alert_state", String(16), nullable=False),
    Column("created_at", Float(precision=53), nullable=False))
schema_version = table("schema_version", Column("version", Integer, primary_key=True))
permission = table("permission", Column("id", Integer, primary_key=True),
    Column("username", String(32), nullable=False), Column("display_name", String(60), nullable=False),
    Column("password_hash", String(255)), Column("requested_role", String(16), nullable=False),
    Column("request_note", String(500), nullable=False), Column("status", String(16), nullable=False, server_default="pending"),
    Column("created_at", Float(precision=53), nullable=False), Column("reviewed_at", Float(precision=53)),
    Column("reviewed_by", Integer, ForeignKey("users.id")), Column("approved_user_id", Integer, ForeignKey("users.id")),
    Column("granted_role", String(16)), Column("review_note", String(500)),
    CheckConstraint("status IN ('pending','approved','rejected')", name="ck_permission_status"),
    CheckConstraint("requested_role IN ('doctor','nurse','coordinator','researcher')", name="ck_permission_requested_role"),
    CheckConstraint("granted_role IS NULL OR granted_role IN ('admin','doctor','nurse','coordinator','researcher')", name="ck_permission_granted_role"))
write_lock = table("auth_write_lock", Column("id", Integer, primary_key=True))
password_resets = table("password_resets", Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", Float(precision=53), nullable=False), Column("expires_at", Float(precision=53), nullable=False),
    Column("issued_by", Integer, ForeignKey("users.id")))
Index("ix_sessions_user_created", sessions.c.user_id, sessions.c.created_at)
Index("ix_assignments_user", assignments.c.user_id)
Index("ix_patient_events_patient_model", patient_events.c.patient_id, patient_events.c.model_profile, patient_events.c.id)
Index("ix_permission_username_status", permission.c.username, permission.c.status)
Index("ix_permission_status_created", permission.c.status, permission.c.created_at)

# Append-only demonstration records; none of these fields feed model inference.
patient_contexts = table("patient_contexts", Column("id", Integer, primary_key=True),
    Column("patient_id", String(32), nullable=False), Column("minute", Integer, nullable=False),
    Column("diagnosis", String(300), nullable=False), Column("admission_reason", Text, nullable=False),
    Column("condition_summary", Text, nullable=False), Column("admission_severity", String(100), nullable=False),
    Column("specialty", String(100), nullable=False), Column("physician_id", Integer, ForeignKey("users.id")),
    Column("actor_id", Integer, ForeignKey("users.id"), nullable=False), Column("created_at", Float(precision=53), nullable=False))
clinical_entries = table("clinical_entries", Column("id", Integer, primary_key=True),
    Column("patient_id", String(32), nullable=False), Column("minute", Integer, nullable=False),
    Column("kind", String(20), nullable=False), Column("assessment", Text, nullable=False),
    Column("plan", Text, nullable=False), Column("follow_up", Text, nullable=False),
    Column("escalation", Text, nullable=False), Column("review_minute", Integer),
    Column("actor_id", Integer, ForeignKey("users.id"), nullable=False), Column("actor_role", String(16), nullable=False),
    Column("created_at", Float(precision=53), nullable=False))
vital_rule_versions = table("vital_rule_versions", Column("id", Integer, primary_key=True),
    Column("patient_id", String(32), nullable=False), Column("minute", Integer, nullable=False),
    Column("rules_json", Text, nullable=False), Column("actor_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("created_at", Float(precision=53), nullable=False))
for clinical_table in (patient_contexts, clinical_entries, vital_rule_versions):
    Index("ix_" + clinical_table.name + "_patient_time", clinical_table.c.patient_id, clinical_table.c.minute, clinical_table.c.id)

follow_up_events = table("follow_up_events", Column("id", Integer, primary_key=True),
    Column("entry_id", Integer, ForeignKey("clinical_entries.id"), nullable=False),
    Column("minute", Integer, nullable=False), Column("status", String(16), nullable=False),
    Column("content", Text, nullable=False), Column("actor_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("actor_role", String(16), nullable=False), Column("created_at", Float(precision=53), nullable=False),
    CheckConstraint("status IN ('pending','completed')", name="ck_follow_up_status"))
Index("ix_follow_up_entry_time", follow_up_events.c.entry_id, follow_up_events.c.minute, follow_up_events.c.id)

doctor_review_requests = table("doctor_review_requests", Column("id", Integer, primary_key=True),
    Column("entry_id", Integer, ForeignKey("clinical_entries.id"), nullable=False, unique=True))
doctor_review_events = table("doctor_review_events", Column("id", Integer, primary_key=True),
    Column("request_id", Integer, ForeignKey("doctor_review_requests.id"), nullable=False),
    Column("minute", Integer, nullable=False), Column("status", String(16), nullable=False),
    Column("content", Text, nullable=False), Column("actor_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("actor_role", String(16), nullable=False), Column("created_at", Float(precision=53), nullable=False),
    CheckConstraint("status IN ('pending','acknowledged','resolved')", name="ck_doctor_review_status"))
Index("ix_doctor_review_request_time", doctor_review_events.c.request_id, doctor_review_events.c.minute, doctor_review_events.c.id)


availability_events = table("availability_events", Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("status", String(16), nullable=False), Column("note", String(300), nullable=False),
    Column("actor_id", Integer, ForeignKey("users.id"), nullable=False), Column("created_at", Float(precision=53), nullable=False),
    CheckConstraint("status IN ('on_duty','off_duty','unavailable')", name="ck_availability_status"))
Index("ix_availability_user", availability_events.c.user_id, availability_events.c.id)
handovers = table("handovers", Column("id", Integer, primary_key=True),
    Column("patient_id", String(32), nullable=False), Column("minute", Integer, nullable=False),
    Column("from_id", Integer, ForeignKey("users.id"), nullable=False), Column("to_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("actor_id", Integer, ForeignKey("users.id"), nullable=False), Column("staff_role", String(16), nullable=False),
    Column("summary", Text, nullable=False), Column("tasks_json", Text, nullable=False),
    Column("created_at", Float(precision=53), nullable=False))
Index("ix_handovers_patient", handovers.c.patient_id, handovers.c.id)
Index("ix_handovers_recipient", handovers.c.to_id, handovers.c.id)
handover_events = table("handover_events", Column("id", Integer, primary_key=True),
    Column("handover_id", Integer, ForeignKey("handovers.id"), nullable=False),
    Column("status", String(16), nullable=False), Column("minute", Integer, nullable=False),
    Column("content", Text, nullable=False), Column("actor_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("created_at", Float(precision=53), nullable=False),
    CheckConstraint("status IN ('accepted','declined','cancelled')", name="ck_handover_status"))
Index("ix_handover_events", handover_events.c.handover_id, handover_events.c.id)


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


class Result:
    def __init__(self, result):
        self.result = result
        self.lastrowid = result.lastrowid

    def fetchone(self):
        row = self.result.fetchone()
        return None if row is None else Row(row._mapping)

    def __iter__(self):
        return (Row(row._mapping) for row in self.result)


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, values=()):
        if sql == "BEGIN IMMEDIATE":
            if self.connection.dialect.name == "sqlite":
                return self.connection.exec_driver_sql(sql)
            # Serialize short access-changing transactions across app processes.
            return self.connection.execute(text("SELECT id FROM auth_write_lock WHERE id=1 FOR UPDATE"))
        parts = sql.split("?")
        if len(parts) - 1 != len(values):
            raise ValueError("SQL parameter count mismatch")
        statement = parts[0] + "".join(f":p{i}" + part for i, part in enumerate(parts[1:]))
        return Result(self.connection.execute(text(statement), {f"p{i}": value for i, value in enumerate(values)}))


class AccountDatabase:
    def __init__(self, location, *, initialize=False):
        if isinstance(location, Path) or "://" not in str(location):
            path = Path(location).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            url = URL.create("sqlite", database=str(path))
        else:
            url = make_url(location)
        if url.drivername not in {"sqlite", "mysql+pymysql"}:
            raise ValueError("Use mysql+pymysql for the project database")
        self.engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800,
                                    hide_parameters=True, echo=False,
                                    connect_args={"timeout": 10} if url.drivername == "sqlite" else
                                    {"connect_timeout": 10, "read_timeout": 15, "write_timeout": 15})
        self.kind = self.engine.dialect.name
        if self.kind == "sqlite":
            @event.listens_for(self.engine, "connect")
            def foreign_keys(connection, record):
                connection.execute("PRAGMA foreign_keys=ON")
        if initialize or self.kind == "sqlite":
            self.initialize_schema()
        with self.engine.connect() as connection:
            versions = list(connection.execute(schema_version.select()).scalars())
            if versions != [SCHEMA_VERSION]:
                raise RuntimeError("Account database schema requires an explicit migration")

    def initialize_schema(self):
        metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            if not connection.execute(schema_version.select()).first():
                connection.execute(schema_version.insert().values(version=SCHEMA_VERSION))
            if not connection.execute(write_lock.select()).first():
                connection.execute(write_lock.insert().values(id=1))

    @contextmanager
    def db(self):
        with self.engine.begin() as connection:
            yield Connection(connection)

    def close(self):
        self.engine.dispose()
