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


@dataclass
class Project:
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    created_at: Optional[str] = None


@dataclass
class Phase:
    id: Optional[int] = None
    project_id: Optional[int] = None
    name: str = ""
    start_date: str = ""
    end_date: str = ""
    status: int = 0  # 0=Not Started, 1=In Progress, 2=Completed
    position: int = 0


@dataclass
class MindMap:
    id: Optional[int] = None
    name: str = ""
    created_at: Optional[str] = None


@dataclass
class MindMapNode:
    id: Optional[int] = None
    mindmap_id: Optional[int] = None
    parent_id: Optional[int] = None
    text: str = "New Idea"
    color: str = "#4488ff"
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    collapsed: bool = False
