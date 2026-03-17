import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from models import Category, Task, Project, Phase, MindMap, MindMapNode

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

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS project_phases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mindmaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS mindmap_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mindmap_id INTEGER NOT NULL,
    parent_id INTEGER DEFAULT NULL,
    text TEXT NOT NULL DEFAULT 'New Idea',
    color TEXT DEFAULT '#4488ff',
    FOREIGN KEY (mindmap_id) REFERENCES mindmaps(id) ON DELETE CASCADE
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

    # ── Stats & Dashboard Queries ───────────────────────────────

    def get_completion_rate(self) -> tuple:
        total = self.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        completed = self.conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE completed = 1"
        ).fetchone()[0]
        return completed, total

    def get_weekly_completions(self) -> dict:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        result = {}
        for i in range(7):
            d = monday + timedelta(days=i)
            count = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE date(completed_at) = ?",
                (d.isoformat(),),
            ).fetchone()[0]
            result[d.strftime("%a")] = count
        return result

    def get_category_stats(self) -> list:
        rows = self.conn.execute(
            """SELECT COALESCE(c.name, 'Uncategorized'),
                      COALESCE(c.color, '#888888'),
                      COUNT(t.id)
               FROM tasks t
               LEFT JOIN categories c ON t.category_id = c.id
               WHERE t.completed = 0
               GROUP BY t.category_id
               ORDER BY COUNT(t.id) DESC"""
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def get_reminders(self, limit: int = 5) -> list[Task]:
        today_str = date.today().isoformat()
        rows = self.conn.execute(
            """SELECT id, title, notes, completed, priority, due_date,
                      category_id, created_at, completed_at
               FROM tasks
               WHERE completed = 0 AND due_date IS NOT NULL AND due_date >= ?
               ORDER BY due_date ASC, priority DESC
               LIMIT ?""",
            (today_str, limit),
        ).fetchall()
        return [
            Task(id=r[0], title=r[1], notes=r[2], completed=bool(r[3]),
                 priority=r[4], due_date=r[5], category_id=r[6],
                 created_at=r[7], completed_at=r[8])
            for r in rows
        ]

    def get_week_tasks(self) -> list:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        result = []
        for i in range(7):
            d = monday + timedelta(days=i)
            d_str = d.isoformat()
            label = f"{d.strftime('%a').upper()} {d.day}"
            rows = self.conn.execute(
                """SELECT id, title, notes, completed, priority, due_date,
                          category_id, created_at, completed_at
                   FROM tasks WHERE due_date = ?
                   ORDER BY completed ASC, priority DESC""",
                (d_str,),
            ).fetchall()
            tasks = [
                Task(id=r[0], title=r[1], notes=r[2], completed=bool(r[3]),
                     priority=r[4], due_date=r[5], category_id=r[6],
                     created_at=r[7], completed_at=r[8])
                for r in rows
            ]
            result.append((label, d_str, tasks))
        return result

    # ── Projects ────────────────────────────────────────────────

    def add_project(self, project: Project) -> int:
        cur = self.conn.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (project.name, project.description),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_project(self, project: Project):
        self.conn.execute(
            "UPDATE projects SET name=?, description=? WHERE id=?",
            (project.name, project.description, project.id),
        )
        self.conn.commit()

    def delete_project(self, project_id: int):
        self.conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        self.conn.commit()

    def get_projects(self) -> list[Project]:
        rows = self.conn.execute(
            "SELECT id, name, description, created_at FROM projects ORDER BY name"
        ).fetchall()
        return [Project(id=r[0], name=r[1], description=r[2], created_at=r[3]) for r in rows]

    # ── Phases ──────────────────────────────────────────────────

    def add_phase(self, phase: Phase) -> int:
        cur = self.conn.execute(
            """INSERT INTO project_phases (project_id, name, start_date, end_date, status, position)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (phase.project_id, phase.name, phase.start_date, phase.end_date,
             phase.status, phase.position),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_phase(self, phase: Phase):
        self.conn.execute(
            """UPDATE project_phases SET name=?, start_date=?, end_date=?, status=?, position=?
               WHERE id=?""",
            (phase.name, phase.start_date, phase.end_date, phase.status, phase.position, phase.id),
        )
        self.conn.commit()

    def delete_phase(self, phase_id: int):
        self.conn.execute("DELETE FROM project_phases WHERE id=?", (phase_id,))
        self.conn.commit()

    def get_phases(self, project_id: int) -> list[Phase]:
        rows = self.conn.execute(
            """SELECT id, project_id, name, start_date, end_date, status, position
               FROM project_phases WHERE project_id=? ORDER BY position, start_date""",
            (project_id,),
        ).fetchall()
        return [Phase(id=r[0], project_id=r[1], name=r[2], start_date=r[3],
                      end_date=r[4], status=r[5], position=r[6]) for r in rows]

    # ── Mind Maps ───────────────────────────────────────────────

    def add_mindmap(self, mm: MindMap) -> int:
        cur = self.conn.execute("INSERT INTO mindmaps (name) VALUES (?)", (mm.name,))
        self.conn.commit()
        mm_id = cur.lastrowid
        self.conn.execute(
            "INSERT INTO mindmap_nodes (mindmap_id, parent_id, text, color) VALUES (?, NULL, ?, ?)",
            (mm_id, mm.name, "#4488ff"),
        )
        self.conn.commit()
        return mm_id

    def update_mindmap(self, mm: MindMap):
        self.conn.execute("UPDATE mindmaps SET name=? WHERE id=?", (mm.name, mm.id))
        self.conn.commit()

    def delete_mindmap(self, mm_id: int):
        self.conn.execute("DELETE FROM mindmaps WHERE id=?", (mm_id,))
        self.conn.commit()

    def get_mindmaps(self) -> list[MindMap]:
        rows = self.conn.execute(
            "SELECT id, name, created_at FROM mindmaps ORDER BY name"
        ).fetchall()
        return [MindMap(id=r[0], name=r[1], created_at=r[2]) for r in rows]

    # ── Mind Map Nodes ──────────────────────────────────────────

    def add_node(self, node: MindMapNode) -> int:
        cur = self.conn.execute(
            "INSERT INTO mindmap_nodes (mindmap_id, parent_id, text, color) VALUES (?, ?, ?, ?)",
            (node.mindmap_id, node.parent_id, node.text, node.color),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_node(self, node: MindMapNode):
        self.conn.execute(
            "UPDATE mindmap_nodes SET text=?, color=? WHERE id=?",
            (node.text, node.color, node.id),
        )
        self.conn.commit()

    def delete_node(self, node_id: int):
        children = self.conn.execute(
            "SELECT id FROM mindmap_nodes WHERE parent_id=?", (node_id,)
        ).fetchall()
        for (child_id,) in children:
            self.delete_node(child_id)
        self.conn.execute("DELETE FROM mindmap_nodes WHERE id=?", (node_id,))
        self.conn.commit()

    def get_nodes(self, mindmap_id: int) -> list[MindMapNode]:
        rows = self.conn.execute(
            "SELECT id, mindmap_id, parent_id, text, color FROM mindmap_nodes WHERE mindmap_id=?",
            (mindmap_id,),
        ).fetchall()
        return [MindMapNode(id=r[0], mindmap_id=r[1], parent_id=r[2],
                            text=r[3], color=r[4]) for r in rows]
