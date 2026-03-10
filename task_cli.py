#!/usr/bin/python3
"""CLI helper to add tasks to the Task Manager database."""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database
from models import Task


def main():
    parser = argparse.ArgumentParser(description="Task Manager CLI")
    sub = parser.add_subparsers(dest="command")

    # Add task
    add_p = sub.add_parser("add", help="Add a new task")
    add_p.add_argument("title", help="Task title")
    add_p.add_argument("--notes", default="", help="Task notes")
    add_p.add_argument("--priority", type=int, choices=[0, 1, 2], default=1,
                       help="Priority: 0=Low, 1=Medium, 2=High")
    add_p.add_argument("--due", default=None, help="Due date (YYYY-MM-DD)")
    add_p.add_argument("--category", default=None, help="Category name")

    # List tasks
    sub.add_parser("list", help="List active tasks")

    # List categories
    sub.add_parser("categories", help="List categories")

    args = parser.parse_args()
    db = Database()

    if args.command == "add":
        category_id = None
        if args.category:
            for cat in db.get_categories():
                if cat.name.lower() == args.category.lower():
                    category_id = cat.id
                    break

        task = Task(
            title=args.title,
            notes=args.notes,
            priority=args.priority,
            due_date=args.due,
            category_id=category_id,
        )
        task_id = db.add_task(task)
        print(f"Added task #{task_id}: {args.title}")
        if args.due:
            print(f"  Due: {args.due}")
        pri_labels = ["Low", "Medium", "High"]
        print(f"  Priority: {pri_labels[args.priority]}")

    elif args.command == "list":
        tasks = db.get_tasks(show_completed=False)
        if not tasks:
            print("No active tasks.")
        else:
            pri = ["Low", "Med", "High"]
            for t in tasks:
                due = f" | Due: {t.due_date}" if t.due_date else ""
                print(f"  [{pri[t.priority]}] {t.title}{due}")

    elif args.command == "categories":
        cats = db.get_categories()
        if not cats:
            print("No categories.")
        else:
            for c in cats:
                print(f"  {c.name} ({c.color})")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
