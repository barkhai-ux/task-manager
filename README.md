# Task Manager

A desktop task management application built with Python, GTK4, and libadwaita. Features a modern dashboard interface with multiple views for organizing tasks, projects, and ideas.

## Features

### Core
- **Add, edit, delete tasks** with title, notes, priority, and due date
- **Mark tasks complete** with completion tracking
- **Persistent storage** using SQLite database
- **Categories** for organizing tasks with custom colors

### Views
- **Dashboard** — overview with completion stats, weekly chart, category breakdown, and upcoming reminders
- **Task List** — filterable by category, sortable by priority/date/title, with search
- **Today / Upcoming** — focused views for time-sensitive tasks
- **Weekly Calendar** — day-by-day task layout for the current week
- **Waterfall (Gantt)** — project phase timeline with drag-to-reorder
- **Mind Map** — interactive canvas for brainstorming with pan/zoom, draggable nodes, collapsible branches, and auto-layout

### Extras
- Dark / Light / System theme switching
- Right-click context menus
- Smooth animations and transitions
- CLI tool for quick task entry from the terminal

## Setup

### Dependencies

- Python 3.10+
- GTK4 and libadwaita

Install on Ubuntu/Debian:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Install on Fedora:

```bash
sudo dnf install python3 python3-gobject gtk4 libadwaita
```

No pip packages required — the app uses only system libraries.

### Run

```bash
python3 main.py
```

### CLI

Add tasks from the terminal without opening the GUI:

```bash
python3 task_cli.py add "Finish report" --priority 2 --due 2026-04-01 --category "Work"
python3 task_cli.py list
python3 task_cli.py categories
```

Priority levels: `0` = Low, `1` = Medium (default), `2` = High

## Project Structure

```
.
├── main.py          # Application window, sidebar, all GTK views
├── database.py      # SQLite database layer (CRUD, queries, migrations)
├── models.py        # Data classes (Task, Category, Project, Phase, MindMap, MindMapNode)
├── dialogs.py       # Dialog windows for creating/editing items
├── mindmap.py       # Interactive mind map canvas (Cairo drawing)
├── waterfall.py     # Waterfall/Gantt chart view
├── style.css        # Theme-adaptive CSS styles
└── task_cli.py      # Command-line interface for quick task management
```

## Usage Examples

**Add a task from the GUI:**
Click the `+` button in the toolbar, fill in the title, priority, due date, and category, then save.

**Organize with categories:**
Create categories from the sidebar (right-click or `+` button). Each category has a custom color and groups related tasks.

**Brainstorm with mind maps:**
Create a mind map from the sidebar. Add child nodes, drag to rearrange, collapse branches, and right-click for quick actions. Use Auto Layout to reorganize.

**Track project timelines:**
Create a project and add phases with start/end dates. View them on the waterfall chart with status indicators.

## Git Workflow

This project was developed using feature branches and pull requests:

- `main` — stable release branch
- `designer` — UI redesign and dark theme ([PR #1](https://github.com/barkhai-ux/task-manager/pull/1))
- `improvement` — mind map enhancements ([PR #2](https://github.com/barkhai-ux/task-manager/pull/2))
