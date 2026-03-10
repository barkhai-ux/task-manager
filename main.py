#!/usr/bin/python3
"""Task Manager — a GTK4/libadwaita to-do application."""

import os
import sys
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, Gdk, Pango

from database import Database
from models import Task, Category
from dialogs import TaskDialog, CategoryDialog

SORT_KEYS = ["priority", "due_date", "title", "created_at"]
PRIORITY_LABELS = ["Low", "Med", "High"]
PRIORITY_CSS = ["priority-low", "priority-medium", "priority-high"]

# Sidebar filter constants
FILTER_ALL = "all"
FILTER_TODAY = "today"
FILTER_UPCOMING = "upcoming"


# ── TaskRow ─────────────────────────────────────────────────────

class TaskRow(Gtk.ListBoxRow):
    """A single task row with checkbox, labels, priority dot, and actions."""

    def __init__(self, task: Task, on_toggle, on_edit, on_delete):
        super().__init__()
        self.task = task

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                       margin_top=6, margin_bottom=6, margin_start=8, margin_end=8)
        self.set_child(hbox)

        # Checkbox
        self.check = Gtk.CheckButton(active=task.completed)
        self.check.connect("toggled", lambda _cb: on_toggle(task))
        hbox.append(self.check)

        # Title + subtitle
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        hbox.append(vbox)

        self.title_label = Gtk.Label(
            label=task.title, xalign=0, ellipsize=Pango.EllipsizeMode.END,
        )
        self.title_label.add_css_class("task-title")
        vbox.append(self.title_label)

        # Subtitle: due date + notes preview
        subtitle_parts = []
        if task.due_date:
            subtitle_parts.append(task.due_date)
        if task.notes:
            preview = task.notes.replace("\n", " ")[:60]
            subtitle_parts.append(preview)

        if subtitle_parts:
            self.subtitle_label = Gtk.Label(
                label=" · ".join(subtitle_parts),
                xalign=0, ellipsize=Pango.EllipsizeMode.END,
            )
            self.subtitle_label.add_css_class("task-subtitle")
            self.subtitle_label.add_css_class("dim-label")
            vbox.append(self.subtitle_label)

            # Mark overdue
            if task.due_date and not task.completed:
                try:
                    if date.fromisoformat(task.due_date) < date.today():
                        self.subtitle_label.add_css_class("overdue")
                except ValueError:
                    pass

        # Priority label
        pri_label = Gtk.Label(label=PRIORITY_LABELS[task.priority])
        pri_label.add_css_class(PRIORITY_CSS[task.priority])
        hbox.append(pri_label)

        # Edit button
        edit_btn = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit")
        edit_btn.add_css_class("flat")
        edit_btn.connect("clicked", lambda _b: on_edit(task))
        hbox.append(edit_btn)

        # Delete button
        del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete")
        del_btn.add_css_class("flat")
        del_btn.connect("clicked", lambda _b: on_delete(task))
        hbox.append(del_btn)

        # Apply completed styling
        if task.completed:
            self.add_css_class("task-completed")


# ── Main Window ─────────────────────────────────────────────────

class TaskManagerWindow(Adw.ApplicationWindow):

    def __init__(self, **kwargs):
        super().__init__(
            default_width=900, default_height=620,
            title="Task Manager", **kwargs,
        )
        self.db = Database()
        self.current_filter = FILTER_ALL
        self.current_category_id = None  # None = all
        self.current_sort = "priority"
        self.show_completed = True

        self._build_ui()
        self.refresh_sidebar()
        self.refresh_task_list()

    # ── UI Construction ─────────────────────────────────────────

    def _build_ui(self):
        # Split view: sidebar + content
        self.split_view = Adw.NavigationSplitView()
        self.set_content(self.split_view)

        # ── Sidebar ──
        sidebar_page = Adw.NavigationPage(title="Tasks")
        sidebar_toolbar = Adw.ToolbarView()
        sidebar_page.set_child(sidebar_toolbar)

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_title(True)
        sidebar_toolbar.add_top_bar(sidebar_header)

        sidebar_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sidebar_toolbar.set_content(sidebar_scroll)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_scroll.set_child(sidebar_box)

        # Virtual filters listbox
        self.filter_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.filter_listbox.add_css_class("navigation-sidebar")
        self.filter_listbox.connect("row-selected", self._on_filter_selected)
        sidebar_box.append(self.filter_listbox)

        self._add_filter_row("All Tasks", FILTER_ALL, "view-list-symbolic")
        self._add_filter_row("Today", FILTER_TODAY, "daytime-sunrise-symbolic")
        self._add_filter_row("Upcoming", FILTER_UPCOMING, "x-office-calendar-symbolic")

        sidebar_box.append(Gtk.Separator())

        # Category header
        cat_header_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
            margin_start=12, margin_end=8, margin_top=10, margin_bottom=4,
        )
        cat_label = Gtk.Label(label="Categories", xalign=0, hexpand=True)
        cat_label.add_css_class("heading")
        cat_header_box.append(cat_label)

        add_cat_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add category")
        add_cat_btn.add_css_class("flat")
        add_cat_btn.connect("clicked", self._on_add_category)
        cat_header_box.append(add_cat_btn)
        sidebar_box.append(cat_header_box)

        # Categories listbox
        self.category_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.category_listbox.add_css_class("navigation-sidebar")
        self.category_listbox.connect("row-selected", self._on_category_selected)
        sidebar_box.append(self.category_listbox)

        self.split_view.set_sidebar(sidebar_page)

        # ── Content ──
        content_page = Adw.NavigationPage(title="All Tasks")
        self.content_page = content_page
        content_toolbar = Adw.ToolbarView()
        content_page.set_child(content_toolbar)

        content_header = Adw.HeaderBar()
        content_toolbar.add_top_bar(content_header)

        # Add task button
        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Task")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add_task)
        content_header.pack_start(add_btn)

        # Header right side: sort + hide completed
        header_right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        content_header.pack_end(header_right)

        # Hide completed toggle
        self.completed_toggle = Gtk.ToggleButton(
            icon_name="object-select-symbolic",
            tooltip_text="Show/hide completed tasks",
            active=True,
        )
        self.completed_toggle.connect("toggled", self._on_toggle_completed)
        header_right.append(self.completed_toggle)

        # Sort dropdown
        sort_model = Gtk.StringList.new(["Priority", "Due Date", "A-Z", "Date Added"])
        self.sort_dropdown = Gtk.DropDown(model=sort_model, tooltip_text="Sort by")
        self.sort_dropdown.connect("notify::selected", self._on_sort_changed)
        header_right.append(self.sort_dropdown)

        # Content stack: list vs empty state
        self.content_stack = Gtk.Stack()
        content_toolbar.set_content(self.content_stack)

        # Task list
        task_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=700)
        task_scroll.set_child(clamp)

        self.task_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.task_listbox.add_css_class("boxed-list")
        clamp.set_child(self.task_listbox)
        self.content_stack.add_named(task_scroll, "list")

        # Empty state
        empty_page = Adw.StatusPage(
            icon_name="checkbox-checked-symbolic",
            title="No Tasks",
            description="Click + to add a new task",
        )
        empty_page.add_css_class("empty-state")
        self.content_stack.add_named(empty_page, "empty")

        self.split_view.set_content(content_page)

        # Select "All Tasks" by default
        self.filter_listbox.select_row(self.filter_listbox.get_row_at_index(0))

    def _add_filter_row(self, label_text, filter_id, icon_name):
        row = Gtk.ListBoxRow()
        row.filter_id = filter_id
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                       margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)
        hbox.append(Gtk.Image(icon_name=icon_name))
        hbox.append(Gtk.Label(label=label_text, xalign=0, hexpand=True))
        self.count_labels = getattr(self, "count_labels", {})
        count_lbl = Gtk.Label(label="0")
        count_lbl.add_css_class("task-count")
        count_lbl.add_css_class("dim-label")
        self.count_labels[filter_id] = count_lbl
        hbox.append(count_lbl)
        row.set_child(hbox)
        self.filter_listbox.append(row)

    # ── Sidebar Events ──────────────────────────────────────────

    def _on_filter_selected(self, listbox, row):
        if row is None:
            return
        # Deselect category listbox
        self.category_listbox.select_row(None)
        self.current_filter = row.filter_id
        self.current_category_id = None
        self.content_page.set_title(row.get_child().get_last_child().get_prev_sibling().get_label()
                                     if hasattr(row, 'filter_id') else "Tasks")
        titles = {FILTER_ALL: "All Tasks", FILTER_TODAY: "Today", FILTER_UPCOMING: "Upcoming"}
        self.content_page.set_title(titles.get(self.current_filter, "Tasks"))
        self.refresh_task_list()

    def _on_category_selected(self, listbox, row):
        if row is None:
            return
        # Deselect filter listbox
        self.filter_listbox.select_row(None)
        self.current_filter = "category"
        self.current_category_id = row.category_id
        self.content_page.set_title(row.category_name)
        self.refresh_task_list()

    # ── Refresh ─────────────────────────────────────────────────

    def refresh_sidebar(self):
        # Clear category rows
        while True:
            row = self.category_listbox.get_row_at_index(0)
            if row is None:
                break
            self.category_listbox.remove(row)

        categories = self.db.get_categories()
        counts = self.db.get_task_counts()

        for cat in categories:
            row = Gtk.ListBoxRow()
            row.category_id = cat.id
            row.category_name = cat.name

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                           margin_start=8, margin_end=8, margin_top=4, margin_bottom=4)

            # Color dot
            dot = Gtk.DrawingArea(
                content_width=12, content_height=12,
                valign=Gtk.Align.CENTER,
            )
            dot._color = cat.color
            dot.set_draw_func(self._draw_category_dot)
            hbox.append(dot)

            hbox.append(Gtk.Label(label=cat.name, xalign=0, hexpand=True))

            count = counts.get(cat.id, 0)
            count_lbl = Gtk.Label(label=str(count))
            count_lbl.add_css_class("task-count")
            count_lbl.add_css_class("dim-label")
            hbox.append(count_lbl)

            row.set_child(hbox)

            # Right-click context menu
            gesture = Gtk.GestureClick(button=3)
            gesture.connect("pressed", self._on_category_right_click, cat)
            row.add_controller(gesture)

            self.category_listbox.append(row)

        # Update filter counts
        all_count = counts.get("all", 0)
        self.count_labels[FILTER_ALL].set_label(str(all_count))

        # Today count
        today_str = date.today().isoformat()
        today_tasks = self.db.get_tasks(show_completed=False)
        today_count = sum(1 for t in today_tasks if t.due_date == today_str)
        self.count_labels[FILTER_TODAY].set_label(str(today_count))

        # Upcoming count
        week_later = (date.today() + timedelta(days=7)).isoformat()
        upcoming_count = sum(
            1 for t in today_tasks
            if t.due_date and today_str <= t.due_date <= week_later
        )
        self.count_labels[FILTER_UPCOMING].set_label(str(upcoming_count))

    def refresh_task_list(self):
        # Clear task list
        while True:
            row = self.task_listbox.get_row_at_index(0)
            if row is None:
                break
            self.task_listbox.remove(row)

        # Get tasks
        tasks = self.db.get_tasks(
            category_id=self.current_category_id,
            show_completed=self.show_completed,
            sort_by=self.current_sort,
        )

        # Apply date filters for virtual categories
        if self.current_filter == FILTER_TODAY:
            today_str = date.today().isoformat()
            tasks = [t for t in tasks if t.due_date == today_str]
        elif self.current_filter == FILTER_UPCOMING:
            today_str = date.today().isoformat()
            week_later = (date.today() + timedelta(days=7)).isoformat()
            tasks = [t for t in tasks if t.due_date and today_str <= t.due_date <= week_later]

        if not tasks:
            self.content_stack.set_visible_child_name("empty")
        else:
            self.content_stack.set_visible_child_name("list")
            for task in tasks:
                row = TaskRow(task,
                              on_toggle=self._on_task_toggled,
                              on_edit=self._on_edit_task,
                              on_delete=self._on_delete_task)
                self.task_listbox.append(row)

    @staticmethod
    def _draw_category_dot(area, cr, width, height):
        color = area._color
        r = int(color[1:3], 16) / 255
        g = int(color[3:5], 16) / 255
        b = int(color[5:7], 16) / 255
        cr.set_source_rgb(r, g, b)
        cr.arc(width / 2, height / 2, min(width, height) / 2, 0, 3.14159 * 2)
        cr.fill()

    # ── Task CRUD ───────────────────────────────────────────────

    def _on_add_task(self, _btn):
        categories = self.db.get_categories()
        dlg = TaskDialog(self, categories, default_category_id=self.current_category_id)
        dlg.set_callback(self._save_new_task)
        dlg.present()

    def _save_new_task(self, task):
        self.db.add_task(task)
        self.refresh_task_list()
        self.refresh_sidebar()

    def _on_edit_task(self, task):
        categories = self.db.get_categories()
        dlg = TaskDialog(self, categories, task=task)
        dlg.set_callback(self._save_edited_task)
        dlg.present()

    def _save_edited_task(self, task):
        self.db.update_task(task)
        self.refresh_task_list()
        self.refresh_sidebar()

    def _on_delete_task(self, task):
        dialog = Adw.MessageDialog(
            heading="Delete Task?",
            body=f'Delete "{task.title}"? This cannot be undone.',
            transient_for=self,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._confirm_delete_task, task.id)
        dialog.present()

    def _confirm_delete_task(self, _dialog, response, task_id):
        if response == "delete":
            self.db.delete_task(task_id)
            self.refresh_task_list()
            self.refresh_sidebar()

    def _on_task_toggled(self, task):
        self.db.toggle_task(task.id)
        self.refresh_task_list()
        self.refresh_sidebar()

    # ── Category CRUD ───────────────────────────────────────────

    def _on_add_category(self, _btn):
        dlg = CategoryDialog(self)
        dlg.set_callback(self._save_new_category)
        dlg.present()

    def _save_new_category(self, category):
        self.db.add_category(category)
        self.refresh_sidebar()

    def _on_category_right_click(self, gesture, _n, x, y, category):
        menu = Gio.Menu()
        menu.append("Edit", f"cat.edit-{category.id}")
        menu.append("Delete", f"cat.delete-{category.id}")

        # Create actions
        action_group = Gio.SimpleActionGroup()

        edit_action = Gio.SimpleAction(name=f"edit-{category.id}")
        edit_action.connect("activate", lambda _a, _p: self._edit_category(category))
        action_group.add_action(edit_action)

        delete_action = Gio.SimpleAction(name=f"delete-{category.id}")
        delete_action.connect("activate", lambda _a, _p: self._delete_category(category))
        action_group.add_action(delete_action)

        row = gesture.get_widget()
        row.insert_action_group("cat", action_group)

        popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=True)
        popover.set_parent(row)
        popover.popup()

    def _edit_category(self, category):
        dlg = CategoryDialog(self, category=category)
        dlg.set_callback(self._save_edited_category)
        dlg.present()

    def _save_edited_category(self, category):
        self.db.update_category(category)
        self.refresh_sidebar()
        self.refresh_task_list()

    def _delete_category(self, category):
        dialog = Adw.MessageDialog(
            heading="Delete Category?",
            body=f'Delete "{category.name}"? Tasks in this category will become uncategorized.',
            transient_for=self,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._confirm_delete_category, category.id)
        dialog.present()

    def _confirm_delete_category(self, _dialog, response, category_id):
        if response == "delete":
            self.db.delete_category(category_id)
            self.current_filter = FILTER_ALL
            self.current_category_id = None
            self.filter_listbox.select_row(self.filter_listbox.get_row_at_index(0))
            self.refresh_sidebar()
            self.refresh_task_list()

    # ── Sort & Filter Controls ──────────────────────────────────

    def _on_sort_changed(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        self.current_sort = SORT_KEYS[idx]
        self.refresh_task_list()

    def _on_toggle_completed(self, btn):
        self.show_completed = btn.get_active()
        self.refresh_task_list()


# ── Application ─────────────────────────────────────────────────

class TaskManagerApp(Adw.Application):

    def __init__(self):
        super().__init__(
            application_id="com.lab7.taskmanager",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
        css.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def do_activate(self):
        win = TaskManagerWindow(application=self)
        win.present()


def main():
    app = TaskManagerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
