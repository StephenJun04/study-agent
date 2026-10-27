"""Small SQL boundary: explicit scopes and transactions, no destructive setup."""

from contextlib import contextmanager
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from langgraph.checkpoint.postgres import PostgresSaver
from .config import ROOT


def uid():
    return str(uuid4())


class DomainError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class Database:
    def __init__(self, settings):
        self.settings = settings

    def connect(self):
        return psycopg.connect(self.settings.database_url, autocommit=True, row_factory=dict_row)

    def migrate(self):
        if self.settings.embedding_dim != 768:
            raise ValueError("This schema pins vector dimension to 768; use a new migration to change it.")
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_lock(7608001)")
            try:
                with conn.transaction():
                    conn.execute((ROOT / "migrations/001_initial.sql").read_text())
                PostgresSaver(conn).setup()
            finally:
                conn.execute("SELECT pg_advisory_unlock(7608001)")

    def one(self, query, params=()):
        with self.connect() as conn:
            return conn.execute(query, params).fetchone()

    def all(self, query, params=()):
        with self.connect() as conn:
            return conn.execute(query, params).fetchall()

    def execute(self, query, params=()):
        with self.connect() as conn:
            return conn.execute(query, params).rowcount

    @contextmanager
    def lock(self, key):
        # Session-level advisory lock covers graph execution across all app processes.
        with self.connect() as conn:
            conn.execute("SET lock_timeout = '3s'")
            try:
                conn.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
            except psycopg.errors.LockNotAvailable as exc:
                raise DomainError("该操作正在处理，请稍后重试。", 409) from exc
            try:
                yield conn
            finally:
                conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,))

    def create_space(self, name, kind, topic):
        return self.one(
            "INSERT INTO spaces(id,owner_id,name,kind,topic) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (uid(), self.settings.user_id, name, kind, topic),
        )

    def space(self, space_id):
        row = self.one("SELECT * FROM spaces WHERE id=%s AND owner_id=%s", (space_id, self.settings.user_id))
        if not row:
            raise DomainError("学习空间不存在或不属于当前用户。", 404)
        return row

    def concept(self, space_id, concept_id):
        self.space(space_id)
        row = self.one("SELECT * FROM concepts WHERE id=%s AND space_id=%s", (concept_id, space_id))
        if not row:
            raise DomainError("概念不属于当前空间。", 404)
        return row

    def session(self, space_id, session_id):
        self.space(space_id)
        row = self.one("SELECT * FROM sessions WHERE id=%s AND space_id=%s", (session_id, space_id))
        if not row:
            raise DomainError("会话不属于当前空间。", 404)
        if row["thread_id"] != f"study:{space_id}:{session_id}":
            raise DomainError("检查点与会话关联无效。", 409)
        return row

    def event(self, space_id, kind, payload, session_id=None):
        self.execute(
            "INSERT INTO events(space_id,session_id,kind,payload) VALUES (%s,%s,%s,%s)",
            (space_id, session_id, kind, Jsonb(payload)),
        )

    def log_call(self, payload):
        self.execute("INSERT INTO model_calls(payload) VALUES (%s)", (Jsonb(payload),))


if __name__ == "__main__":
    from .config import Settings

    Database(Settings()).migrate()
    print("StudyAgent migrations applied (non-destructive).")
