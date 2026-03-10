from dataclasses import dataclass
from typing import Optional


@dataclass
class Category:
    id: Optional[int] = None
    name: str = ""
    color: str = "#3584e4"
    position: int = 0


@dataclass
class Task:
    id: Optional[int] = None
    title: str = ""
    notes: str = ""
    completed: bool = False
    priority: int = 1  # 0=Low, 1=Medium, 2=High
    due_date: Optional[str] = None  # "YYYY-MM-DD" or None
    category_id: Optional[int] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
