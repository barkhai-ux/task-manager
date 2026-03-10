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
PRIORITY_LABELS = ["High", "Med", "Low"]
PRIORITY_CSS = ["priority-low", "priority-medium", "priority-high"]

FILTER_ALL = "all"
FILTER_TODAY = "today"
FILTER_UPCOMING = "upcoming"

SCHEME_NAMES = ["System", "Light", "Dark"]
SCHEME_VALUES = [
    Adw.ColorScheme.DEFAULT,
    Adw.ColorScheme.FORCE_LIGHT,
    Adw.ColorScheme.FORCE_DARK,
]
SCHEME_STR = ["default", "force_light", "force_dark"]


# ── TaskRow ─────────────────────────────────────────────────────

class TaskRow(Gtk.ListBoxRow):
    """A polished task row with checkbox, info, badges, and actions."""

    def __init__(self, task: Task, category_color: str, on_toggle, on_edit, on_delete):
        super().__init__()
        self.task = task
        self.add_css_class("task-row")

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                       margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.set_child(hbox)

        # Category color bar (thin vertical stripe)
        if category_color:
            bar = Gtk.DrawingArea(content_width=4, content_height=36,
                                 valign=Gtk.Align.CENTER)
            bar._color = category_color
            bar.set_draw_func(self._draw_color_bar)
            hbox.append(bar)

        # Checkbox
        self.check = Gtk.CheckButton(active=task.completed, valign=Gtk.Align.CENTER)
        self.check.connect("toggled", lambda _cb: on_toggle(task))
        hbox.append(self.check)

        # Title + subtitle
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True,
                       valign=Gtk.Align.CENTER)
        hbox.append(vbox)

        self.title_label = Gtk.Label(
            label=task.title, xalign=0, ellipsize=Pango.EllipsizeMode.END,
        )
        self.title_label.add_css_class("task-title")
        vbox.append(self.title_label)

        # Subtitle line: notes preview
        if task.notes:
            preview = task.notes.replace("\n", " ")[:80]
            sub = Gtk.Label(label=preview, xalign=0, ellipsize=Pango.EllipsizeMode.END)
            sub.add_css_class("task-subtitle")
            sub.add_css_class("dim-label")
            vbox.append(sub)

        # Badges box (due date + priority)
        badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                         valign=Gtk.Align.CENTER)
        hbox.append(badges)

        # Due date badge
        if task.due_date:
            due_label = self._make_due_badge(task.due_date, task.completed)
            badges.append(due_label)

        # Priority badge
        pri_names = ["Low", "Med", "High"]
        pri_label = Gtk.Label(label=pri_names[task.priority], xalign=0.5)
        pri_label.add_css_class("priority-badge")
        pri_label.add_css_class(PRIORITY_CSS[task.priority])
        badges.append(pri_label)

        # Action buttons
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2,
                          valign=Gtk.Align.CENTER)
        actions.add_css_class("task-actions")
        hbox.append(actions)

        edit_btn = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit")
        edit_btn.add_css_class("flat")
        edit_btn.connect("clicked", lambda _b: on_edit(task))
        actions.append(edit_btn)

        del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete")
        del_btn.add_css_class("flat")
        del_btn.add_css_class("delete-btn")
        del_btn.connect("clicked", lambda _b: on_delete(task))
        actions.append(del_btn)

        if task.completed:
            self.add_css_class("task-completed")

    def _make_due_badge(self, due_str, completed):
        today = date.today()
        try:
            due = date.fromisoformat(due_str)
        except ValueError:
            due = None

        label = Gtk.Label(xalign=0.5)
        label.add_css_class("due-badge")

        if due is None:
            label.set_label(due_str)
        elif completed:
            label.set_label(due_str)
        elif due < today:
            days = (today - due).days
            label.set_label(f"{days}d overdue")
            label.add_css_class("overdue")
        elif due == today:
            label.set_label("Today")
            label.add_css_class("due-today")
        elif due == today + timedelta(days=1):
            label.set_label("Tomorrow")
        else:
            label.set_label(due_str)
        return label

    @staticmethod
    def _draw_color_bar(area, cr, width, height):
        color = area._color
        r = int(color[1:3], 16) / 255
        g = int(color[3:5], 16) / 255
        b = int(color[5:7], 16) / 255
        cr.set_source_rgb(r, g, b)
        cr.rectangle(0, 2, width, height - 4)
        cr.fill()


# ── Main Window ─────────────────────────────────────────────────

class TaskManagerWindow(Adw.ApplicationWindow):

    def __init__(self, **kwargs):
        super().__init__(
            default_width=950, default_height=650,
            title="Task Manager", **kwargs,
        )
        self.db = Database()
        self.current_filter = FILTER_ALL
        self.current_category_id = None
        self.current_sort = "priority"
        self.show_completed = True
        self._category_colors = {}  # category_id -> color hex

        self._build_ui()
        self._load_theme()
        self.refresh_sidebar()
        self.refresh_task_list()

    def _load_theme(self):
        saved = self.db.get_setting("color_scheme", "default")
        idx = 0
        if saved in SCHEME_STR:
            idx = SCHEME_STR.index(saved)
        Adw.StyleManager.get_default().set_color_scheme(SCHEME_VALUES[idx])
        self._theme_loading = True
        self.theme_buttons[idx].set_active(True)
        self._theme_loading = False

    # ── UI Construction ─────────────────────────────────────────

    def _build_ui(self):
        self.split_view = Adw.NavigationSplitView()
        self.set_content(self.split_view)

        # ── Sidebar ──
        sidebar_page = Adw.NavigationPage(title="Task Manager")
        sidebar_toolbar = Adw.ToolbarView()
        sidebar_page.set_child(sidebar_toolbar)

        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_title(True)
        sidebar_toolbar.add_top_bar(sidebar_header)

        sidebar_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                            vexpand=True)
        sidebar_toolbar.set_content(sidebar_scroll)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_scroll.set_child(sidebar_box)

        # ── Filters section ──
        filters_label = Gtk.Label(label="FILTERS", xalign=0,
                                  margin_start=16, margin_top=12, margin_bottom=4)
        filters_label.add_css_class("sidebar-section-title")
        sidebar_box.append(filters_label)

        self.filter_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.filter_listbox.add_css_class("navigation-sidebar")
        self.filter_listbox.connect("row-selected", self._on_filter_selected)
        sidebar_box.append(self.filter_listbox)

        self.count_labels = {}
        self._add_filter_row("All Tasks", FILTER_ALL, "view-list-symbolic")
        self._add_filter_row("Today", FILTER_TODAY, "alarm-symbolic")
        self._add_filter_row("Upcoming", FILTER_UPCOMING, "x-office-calendar-symbolic")

        sidebar_box.append(Gtk.Separator(margin_top=8, margin_bottom=4))

        # ── Categories section ──
        cat_header_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
            margin_start=16, margin_end=8, margin_top=8, margin_bottom=4,
        )
        cat_label = Gtk.Label(label="CATEGORIES", xalign=0, hexpand=True)
        cat_label.add_css_class("sidebar-section-title")
        cat_header_box.append(cat_label)

        add_cat_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add category")
        add_cat_btn.add_css_class("flat")
        add_cat_btn.connect("clicked", self._on_add_category)
        cat_header_box.append(add_cat_btn)
        sidebar_box.append(cat_header_box)

        self.category_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.category_listbox.add_css_class("navigation-sidebar")
        self.category_listbox.connect("row-selected", self._on_category_selected)
        sidebar_box.append(self.category_listbox)

        sidebar_box.append(Gtk.Separator(margin_top=8, margin_bottom=4))

        # ── Theme section ──
        theme_label = Gtk.Label(label="APPEARANCE", xalign=0,
                                margin_start=16, margin_top=8, margin_bottom=6)
        theme_label.add_css_class("sidebar-section-title")
        sidebar_box.append(theme_label)

        theme_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                            margin_start=12, margin_end=12, margin_bottom=12,
                            halign=Gtk.Align.CENTER, homogeneous=True)
        theme_box.add_css_class("linked")
        sidebar_box.append(theme_box)

        self.theme_buttons = []
        icons = ["weather-clear-symbolic", "display-brightness-symbolic", "weather-clear-night-symbolic"]
        for i, name in enumerate(SCHEME_NAMES):
            btn = Gtk.ToggleButton(tooltip_text=name)
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                              halign=Gtk.Align.CENTER)
            btn_box.append(Gtk.Image(icon_name=icons[i]))
            btn_box.append(Gtk.Label(label=name))
            btn.set_child(btn_box)
            btn.add_css_class("theme-btn")
            btn.connect("toggled", self._on_theme_toggled, i)
            theme_box.append(btn)
            self.theme_buttons.append(btn)

        self.split_view.set_sidebar(sidebar_page)

        # ── Content ──
        content_page = Adw.NavigationPage(title="All Tasks")
        self.content_page = content_page
        content_toolbar = Adw.ToolbarView()
        content_page.set_child(content_toolbar)

        content_header = Adw.HeaderBar()
        content_toolbar.add_top_bar(content_header)

        # Add task button with label
        add_btn = Gtk.Button(tooltip_text="Add Task")
        add_btn.add_css_class("suggested-action")
        add_btn.add_css_class("add-task-btn")
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_box.append(Gtk.Image(icon_name="list-add-symbolic"))
        add_box.append(Gtk.Label(label="Add Task"))
        add_btn.set_child(add_box)
        add_btn.connect("clicked", self._on_add_task)
        content_header.pack_start(add_btn)

        # Header right side
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

        # Content stack
        self.content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        content_toolbar.set_content(self.content_stack)

        # Task list
        task_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=750, margin_top=8, margin_bottom=8)
        task_scroll.set_child(clamp)

        self.task_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.task_listbox.add_css_class("boxed-list")
        clamp.set_child(self.task_listbox)
        self.content_stack.add_named(task_scroll, "list")

        # Empty state
        empty_page = Adw.StatusPage(
            icon_name="checkbox-checked-symbolic",
            title="No Tasks",
            description='Click "Add Task" to create your first task',
        )
        empty_page.add_css_class("empty-state")
        self.content_stack.add_named(empty_page, "empty")

        self.split_view.set_content(content_page)

        # Select "All Tasks" by default
        self.filter_listbox.select_row(self.filter_listbox.get_row_at_index(0))

    def _add_filter_row(self, label_text, filter_id, icon_name):
        row = Gtk.ListBoxRow()
        row.filter_id = filter_id
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                       margin_start=10, margin_end=10, margin_top=5, margin_bottom=5)
        hbox.append(Gtk.Image(icon_name=icon_name))
        lbl = Gtk.Label(label=label_text, xalign=0, hexpand=True)
        hbox.append(lbl)

        count_lbl = Gtk.Label(label="0")
        count_lbl.add_css_class("count-badge")
        count_lbl.add_css_class("count-badge-zero")
        self.count_labels[filter_id] = count_lbl
        hbox.append(count_lbl)

        row.set_child(hbox)
        self.filter_listbox.append(row)

    # ── Theme ───────────────────────────────────────────────────

    def _on_theme_toggled(self, btn, idx):
        if getattr(self, '_theme_loading', False):
            return
        if not btn.get_active():
            return

        # Deactivate other buttons
        self._theme_loading = True
        for i, b in enumerate(self.theme_buttons):
            if i != idx:
                b.set_active(False)
        self._theme_loading = False

        # Apply and save
        Adw.StyleManager.get_default().set_color_scheme(SCHEME_VALUES[idx])
        self.db.set_setting("color_scheme", SCHEME_STR[idx])

    # ── Sidebar Events ──────────────────────────────────────────

    def _on_filter_selected(self, listbox, row):
        if row is None:
            return
        self.category_listbox.select_row(None)
        self.current_filter = row.filter_id
        self.current_category_id = None
        titles = {FILTER_ALL: "All Tasks", FILTER_TODAY: "Today", FILTER_UPCOMING: "Upcoming"}
        self.content_page.set_title(titles.get(self.current_filter, "Tasks"))
        self.refresh_task_list()

    def _on_category_selected(self, listbox, row):
        if row is None:
            return
        self.filter_listbox.select_row(None)
        self.current_filter = "category"
        self.current_category_id = row.category_id
        self.content_page.set_title(row.category_name)
        self.refresh_task_list()

    # ── Refresh ─────────────────────────────────────────────────

    def refresh_sidebar(self):
        while True:
            row = self.category_listbox.get_row_at_index(0)
            if row is None:
                break
            self.category_listbox.remove(row)

        categories = self.db.get_categories()
        counts = self.db.get_task_counts()

        # Cache category colors
        self._category_colors = {c.id: c.color for c in categories}

        for cat in categories:
            row = Gtk.ListBoxRow()
            row.category_id = cat.id
            row.category_name = cat.name

            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                           margin_start=10, margin_end=10, margin_top=5, margin_bottom=5)

            # Color dot
            dot = Gtk.DrawingArea(content_width=12, content_height=12,
                                  valign=Gtk.Align.CENTER)
            dot._color = cat.color
            dot.set_draw_func(self._draw_category_dot)
            hbox.append(dot)

            hbox.append(Gtk.Label(label=cat.name, xalign=0, hexpand=True))

            count = counts.get(cat.id, 0)
            count_lbl = Gtk.Label(label=str(count))
            count_lbl.add_css_class("count-badge")
            if count == 0:
                count_lbl.add_css_class("count-badge-zero")
            hbox.append(count_lbl)

            row.set_child(hbox)

            gesture = Gtk.GestureClick(button=3)
            gesture.connect("pressed", self._on_category_right_click, cat)
            row.add_controller(gesture)

            self.category_listbox.append(row)

        # Update filter counts
        all_count = counts.get("all", 0)
        self._update_count_label(FILTER_ALL, all_count)

        today_str = date.today().isoformat()
        all_tasks = self.db.get_tasks(show_completed=False)
        today_count = sum(1 for t in all_tasks if t.due_date == today_str)
        self._update_count_label(FILTER_TODAY, today_count)

        week_later = (date.today() + timedelta(days=7)).isoformat()
        upcoming_count = sum(
            1 for t in all_tasks
            if t.due_date and today_str <= t.due_date <= week_later
        )
        self._update_count_label(FILTER_UPCOMING, upcoming_count)

    def _update_count_label(self, filter_id, count):
        lbl = self.count_labels[filter_id]
        lbl.set_label(str(count))
        if count == 0:
            lbl.add_css_class("count-badge-zero")
        else:
            lbl.remove_css_class("count-badge-zero")

    def refresh_task_list(self):
        while True:
            row = self.task_listbox.get_row_at_index(0)
            if row is None:
                break
            self.task_listbox.remove(row)

        tasks = self.db.get_tasks(
            category_id=self.current_category_id,
            show_completed=self.show_completed,
            sort_by=self.current_sort,
        )

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
                cat_color = self._category_colors.get(task.category_id)
                row = TaskRow(task,
                              category_color=cat_color,
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
            body=f'Delete "{category.name}"? Tasks will become uncategorized.',
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

        # Apply saved theme before any window is shown
        db = Database()
        saved = db.get_setting("color_scheme", "default")
        idx = SCHEME_STR.index(saved) if saved in SCHEME_STR else 0
        Adw.StyleManager.get_default().set_color_scheme(SCHEME_VALUES[idx])

        # Load CSS
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
