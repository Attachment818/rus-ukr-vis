from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.config import get_settings


class DBSession:
    """Thin wrapper so existing code can use conn.execute(...).fetchone()."""

    def __init__(self, connection: pymysql.connections.Connection) -> None:
        self._connection = connection
        self._cursor = connection.cursor()

    @staticmethod
    def _sql(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, params: tuple | list | None = None) -> DBSession:
        self._cursor.execute(self._sql(query), params or ())
        return self

    def executemany(self, query: str, params_seq: list[tuple | list]) -> DBSession:
        self._cursor.executemany(self._sql(query), params_seq)
        return self

    def fetchone(self) -> dict[str, Any] | None:
        return self._cursor.fetchone()

    def fetchall(self) -> list[dict[str, Any]]:
        return self._cursor.fetchall()

    @property
    def lastrowid(self) -> int:
        return int(self._cursor.lastrowid)


class Database:
    def __init__(self) -> None:
        self.settings = get_settings()

    def connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.settings.mysql_host,
            port=self.settings.mysql_port,
            user=self.settings.mysql_user,
            password=self.settings.mysql_password,
            database=self.settings.mysql_database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    def init(self) -> None:
        with self.session() as conn:
            conn.execute("SELECT 1")
            self._ensure_document_chunk_metadata_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    document_id BIGINT NOT NULL,
                    chunk_id BIGINT NOT NULL,
                    model VARCHAR(255) NOT NULL,
                    dimension INT NOT NULL,
                    embedding_json LONGTEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_chunk_embedding_model (chunk_id, model),
                    INDEX idx_chunk_embeddings_document (document_id),
                    CONSTRAINT fk_chunk_embeddings_document
                        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
                    CONSTRAINT fk_chunk_embeddings_chunk
                        FOREIGN KEY (chunk_id) REFERENCES document_chunks (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    workspace_id BIGINT NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'active',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_chat_sessions_workspace (workspace_id),
                    CONSTRAINT fk_chat_sessions_workspace
                        FOREIGN KEY (workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    session_id BIGINT NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content LONGTEXT NOT NULL,
                    sources_json LONGTEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_chat_messages_session (session_id),
                    CONSTRAINT fk_chat_messages_session
                        FOREIGN KEY (session_id) REFERENCES chat_sessions (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_cases (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    title VARCHAR(500) NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'created',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_case_documents (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    role VARCHAR(100) NULL DEFAULT 'material',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_case_document (case_id, document_id),
                    INDEX idx_case_documents_case (case_id),
                    INDEX idx_case_documents_document (document_id),
                    CONSTRAINT fk_case_documents_case
                        FOREIGN KEY (case_id) REFERENCES intelligence_cases (id) ON DELETE CASCADE,
                    CONSTRAINT fk_case_documents_document
                        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_entities (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    chunk_id BIGINT NULL,
                    name VARCHAR(255) NOT NULL,
                    normalized_name VARCHAR(255) NULL,
                    entity_type VARCHAR(100) NOT NULL,
                    evidence_text TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_intel_entities_case (case_id),
                    INDEX idx_intel_entities_document (document_id),
                    INDEX idx_intel_entities_chunk (chunk_id),
                    CONSTRAINT fk_intel_entities_case
                        FOREIGN KEY (case_id) REFERENCES intelligence_cases (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_entities_document
                        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_entities_chunk
                        FOREIGN KEY (chunk_id) REFERENCES document_chunks (id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_events (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    chunk_id BIGINT NULL,
                    event_title VARCHAR(500) NOT NULL,
                    event_date DATE NULL,
                    event_time_raw VARCHAR(100) NULL,
                    event_type VARCHAR(100) NULL,
                    location_name VARCHAR(255) NULL,
                    actor_names TEXT NULL,
                    summary TEXT NULL,
                    evidence_text TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_intel_events_case (case_id),
                    INDEX idx_intel_events_date (event_date),
                    INDEX idx_intel_events_document (document_id),
                    CONSTRAINT fk_intel_events_case
                        FOREIGN KEY (case_id) REFERENCES intelligence_cases (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_events_document
                        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_events_chunk
                        FOREIGN KEY (chunk_id) REFERENCES document_chunks (id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_relations (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    case_id BIGINT NOT NULL,
                    source_entity_id BIGINT NOT NULL,
                    target_entity_id BIGINT NOT NULL,
                    chunk_id BIGINT NULL,
                    relation_type VARCHAR(100) NOT NULL,
                    evidence_text TEXT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_intel_relation (
                        case_id, source_entity_id, target_entity_id, relation_type
                    ),
                    INDEX idx_intel_relations_case (case_id),
                    CONSTRAINT fk_intel_relations_case
                        FOREIGN KEY (case_id) REFERENCES intelligence_cases (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_relations_source
                        FOREIGN KEY (source_entity_id) REFERENCES intelligence_entities (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_relations_target
                        FOREIGN KEY (target_entity_id) REFERENCES intelligence_entities (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_relations_chunk
                        FOREIGN KEY (chunk_id) REFERENCES document_chunks (id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intelligence_evidences (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    case_id BIGINT NOT NULL,
                    document_id BIGINT NOT NULL,
                    chunk_id BIGINT NULL,
                    evidence_type VARCHAR(100) NOT NULL,
                    quote_text TEXT NULL,
                    source_label VARCHAR(255) NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    INDEX idx_intel_evidences_case (case_id),
                    INDEX idx_intel_evidences_document (document_id),
                    CONSTRAINT fk_intel_evidences_case
                        FOREIGN KEY (case_id) REFERENCES intelligence_cases (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_evidences_document
                        FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
                    CONSTRAINT fk_intel_evidences_chunk
                        FOREIGN KEY (chunk_id) REFERENCES document_chunks (id) ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

    def _column_exists(self, conn: DBSession, table_name: str, column_name: str) -> bool:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = ?
              AND COLUMN_NAME = ?
            """,
            (table_name, column_name),
        ).fetchone()
        return bool(row and int(row["c"]) > 0)

    def _ensure_document_chunk_metadata_columns(self, conn: DBSession) -> None:
        table = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'document_chunks'
            """
        ).fetchone()
        if not table or int(table["c"]) <= 0:
            return
        if not self._column_exists(conn, "document_chunks", "source_path"):
            conn.execute("ALTER TABLE document_chunks ADD COLUMN source_path VARCHAR(1000) NULL DEFAULT NULL")
        if not self._column_exists(conn, "document_chunks", "file_modified_at"):
            conn.execute("ALTER TABLE document_chunks ADD COLUMN file_modified_at DATETIME NULL DEFAULT NULL")
        if not self._column_exists(conn, "document_chunks", "start_offset"):
            conn.execute("ALTER TABLE document_chunks ADD COLUMN start_offset INT NULL DEFAULT NULL")
        if not self._column_exists(conn, "document_chunks", "end_offset"):
            conn.execute("ALTER TABLE document_chunks ADD COLUMN end_offset INT NULL DEFAULT NULL")

    @contextmanager
    def session(self):
        connection = self.connect()
        wrapper = DBSession(connection)
        try:
            yield wrapper
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


@lru_cache(maxsize=1)
def get_database() -> Database:
    database = Database()
    database.init()
    return database
