"""Generic SQLite CRUD for admin tables."""

import sqlite3
from datetime import datetime
from uuid import uuid4


def _mask_value(value: str) -> str:
    """Mask a secret value: show first 3 and last 4 chars."""
    if not value or len(value) <= 8:
        return "***"
    return f"{value[:3]}***...{value[-4:]}"


class CrudTable:
    """Generic CRUD operations for a SQLite table."""

    def __init__(self, db_path: str, table: str):
        self.db_path = db_path
        self.table = table

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list(self, mask_fields: list[str] | None = None) -> list[dict]:
        """List all rows. Optionally mask specified fields."""
        conn = self._conn()
        try:
            rows = conn.execute(f"SELECT * FROM {self.table}").fetchall()
            results = [dict(r) for r in rows]
            if mask_fields:
                for row in results:
                    for field in mask_fields:
                        if field in row and row[field]:
                            row[field] = _mask_value(row[field])
            return results
        finally:
            conn.close()

    def get(self, id_value: str) -> dict | None:
        """Get a single row by primary key."""
        conn = self._conn()
        try:
            pk_col = self._pk_column(conn)
            row = conn.execute(
                f"SELECT * FROM {self.table} WHERE {pk_col} = ?", (id_value,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create(self, data: dict) -> dict:
        """Insert a new row. Auto-generates 'id' if table has an id column."""
        conn = self._conn()
        try:
            pk_col = self._pk_column(conn)
            if pk_col == "id" and "id" not in data:
                data["id"] = uuid4().hex[:12]
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" for _ in data)
            conn.execute(
                f"INSERT INTO {self.table} ({cols}) VALUES ({placeholders})",
                list(data.values()),
            )
            conn.commit()
            return self.get(data[pk_col])
        finally:
            conn.close()

    def update(self, id_value: str, data: dict) -> dict | None:
        """Update a row by primary key."""
        conn = self._conn()
        try:
            pk_col = self._pk_column(conn)
            data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            set_clause = ", ".join(f"{k} = ?" for k in data)
            conn.execute(
                f"UPDATE {self.table} SET {set_clause} WHERE {pk_col} = ?",
                [*data.values(), id_value],
            )
            conn.commit()
            return self.get(id_value)
        finally:
            conn.close()

    def delete(self, id_value: str) -> bool:
        """Delete a row by primary key. Returns True if deleted."""
        conn = self._conn()
        try:
            pk_col = self._pk_column(conn)
            cursor = conn.execute(
                f"DELETE FROM {self.table} WHERE {pk_col} = ?", (id_value,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def _pk_column(self, conn: sqlite3.Connection) -> str:
        """Get the primary key column name for this table."""
        info = conn.execute(f"PRAGMA table_info({self.table})").fetchall()
        for col in info:
            if col["pk"] == 1:
                return col["name"]
        return "id"
