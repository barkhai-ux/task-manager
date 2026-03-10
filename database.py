import os
import sqlite3
from datetime import datetime
from typing import Optional

from models import Category, Task

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#3584e4',
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    notes TEXT DEFAULT '',
    completed INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 1,
    due_date TEXT DEFAULT NULL,
    category_id INTEGER DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    completed_at TEXT DEFAULT NULL,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SORT_CLAUSES = {
    "priority": "ORDER BY completed ASC, priority DESC, due_date ASC",
    "due_date": "ORDER BY completed ASC, CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC",
    "title": "ORDER BY completed ASC, title COLLATE NOCASE ASC",
    "created_at": "ORDER BY completed ASC, created_at DESC",
}


class Database:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = os.path.join(
                os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                "task-manager",
            )
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "tasks.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # ── Categories ──────────────────────────────────────────────

    def add_category(self, category: Category) -> int:
        cur = self.conn.execute(
            "INSERT INTO categories (name, color, position) VALUES (?, ?, ?)",
            (category.name, category.color, category.position),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_category(self, category: Category):
        self.conn.execute(
            "UPDATE categories SET name=?, color=?, position=? WHERE id=?",
            (category.name, category.color, category.position, category.id),
        )
        self.conn.commit()

    def delete_category(self, category_id: int):
        self.conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
        self.conn.commit()

    def get_categories(self) -> list[Category]:
        rows = self.conn.execute(
            "SELECT id, name, color, position FROM categories ORDER BY position, name"
        ).fetchall()
        return [Category(id=r[0], name=r[1], color=r[2], position=r[3]) for r in rows]

    def get_category(self, category_id: int) -> Optional[Category]:
        r = self.conn.execute(
            "SELECT id, name, color, position FROM categories WHERE id=?",
            (category_id,),
        ).fetchone()
        if r:
            return Category(id=r[0], name=r[1], color=r[2], position=r[3])
        return None

    # ── Tasks ───────────────────────────────────────────────────

    def add_task(self, task: Task) -> int:
        cur = self.conn.execute(
            """INSERT INTO tasks (title, notes, completed, priority, due_date, category_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (task.title, task.notes, int(task.completed), task.priority,
             task.due_date, task.category_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_task(self, task: Task):
        self.conn.execute(
            """UPDATE tasks SET title=?, notes=?, completed=?, priority=?,
               due_date=?, category_id=?, completed_at=? WHERE id=?""",
            (task.title, task.notes, int(task.completed), task.priority,
             task.due_date, task.category_id, task.completed_at, task.id),
        )
        self.conn.commit()

    def delete_task(self, task_id: int):
        self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    def toggle_task(self, task_id: int) -> bool:
        row = self.conn.execute(
            "SELECT completed FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        if row is None:
            return False
        new_state = 0 if row[0] else 1
        completed_at = datetime.now().isoformat() if new_state else None
        self.conn.execute(
            "UPDATE tasks SET completed=?, completed_at=? WHERE id=?",
            (new_state, completed_at, task_id),
        )
        self.conn.commit()
        return bool(new_state)

    def get_tasks(
        self,
        category_id: Optional[int] = None,
        show_completed: bool = True,
        sort_by: str = "priority",
    ) -> list[Task]:
        conditions = []
        params = []

        if category_id is not None:
            if category_id == -1:
                conditions.append("category_id IS NULL")
            else:
                conditions.append("category_id = ?")
                params.append(category_id)

        if not show_completed:
            conditions.append("completed = 0")

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        order = SORT_CLAUSES.get(sort_by, SORT_CLAUSES["priority"])

        rows = self.conn.execute(
            f"""SELECT id, title, notes, completed, priority, due_date,
                       category_id, created_at, completed_at
                FROM tasks {where} {order}""",
            params,
        ).fetchall()

        return [
            Task(
                id=r[0], title=r[1], notes=r[2], completed=bool(r[3]),
                priority=r[4], due_date=r[5], category_id=r[6],
                created_at=r[7], completed_at=r[8],
            )
            for r in rows
        ]

    def get_task(self, task_id: int) -> Optional[Task]:
        r = self.conn.execute(
            """SELECT id, title, notes, completed, priority, due_date,
                      category_id, created_at, completed_at
               FROM tasks WHERE id=?""",
            (task_id,),
        ).fetchone()
        if r:
            return Task(
                id=r[0], title=r[1], notes=r[2], completed=bool(r[3]),
                priority=r[4], due_date=r[5], category_id=r[6],
                created_at=r[7], completed_at=r[8],
            )
        return None

    def get_task_counts(self) -> dict:
        rows = self.conn.execute(
            """SELECT category_id, COUNT(*) FROM tasks
               WHERE completed = 0 GROUP BY category_id"""
        ).fetchall()
        counts = {r[0]: r[1] for r in rows}
        total = self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE completed = 0"
        ).fetchone()[0]
        counts["all"] = total
        return counts

    # ── Settings ────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()
