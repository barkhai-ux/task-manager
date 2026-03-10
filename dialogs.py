import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

from models import Task, Category


class TaskDialog(Adw.Window):
    """Dialog for adding or editing a task."""

    def __init__(self, parent, categories: list[Category],
                 task: Task = None, default_category_id=None):
        super().__init__(
            modal=True,
            transient_for=parent,
            default_width=450,
            default_height=520,
            title="Edit Task" if task else "New Task",
        )
        self.task = task
        self.categories = categories
        self.callback = None
        self._selected_date = task.due_date if task else None

        # Main layout
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # Header bar with cancel/save
        header = Adw.HeaderBar()
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)
        toolbar_view.add_top_bar(header)

        # Content
        scroll = Gtk.ScrolledWindow(vexpand=True)
        toolbar_view.set_content(scroll)

        clamp = Adw.Clamp(maximum_size=400, margin_top=12, margin_bottom=12,
                          margin_start=12, margin_end=12)
        scroll.set_child(clamp)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp.set_child(box)

        # Title
        title_group = Adw.PreferencesGroup(title="Title")
        self.title_row = Adw.EntryRow(title="Task title")
        if task:
            self.title_row.set_text(task.title)
        title_group.add(self.title_row)
        box.append(title_group)

        # Notes
        notes_group = Adw.PreferencesGroup(title="Notes")
        notes_frame = Gtk.Frame()
        self.notes_view = Gtk.TextView(
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            height_request=80,
            top_margin=8, bottom_margin=8, left_margin=8, right_margin=8,
        )
        if task and task.notes:
            self.notes_view.get_buffer().set_text(task.notes)
        notes_frame.set_child(self.notes_view)
        notes_group.add(notes_frame)
        box.append(notes_group)

        # Category & Priority
        details_group = Adw.PreferencesGroup(title="Details")

        # Category dropdown
        cat_names = ["None"] + [c.name for c in categories]
        cat_model = Gtk.StringList.new(cat_names)
        self.category_row = Adw.ComboRow(title="Category", model=cat_model)
        # Set default selection
        selected_cat = 0
        if task and task.category_id is not None:
            for i, c in enumerate(categories):
                if c.id == task.category_id:
                    selected_cat = i + 1
                    break
        elif default_category_id is not None:
            for i, c in enumerate(categories):
                if c.id == default_category_id:
                    selected_cat = i + 1
                    break
        self.category_row.set_selected(selected_cat)
        details_group.add(self.category_row)

        # Priority dropdown
        priority_model = Gtk.StringList.new(["Low", "Medium", "High"])
        self.priority_row = Adw.ComboRow(title="Priority", model=priority_model)
        self.priority_row.set_selected(task.priority if task else 1)
        details_group.add(self.priority_row)

        box.append(details_group)

        # Due date
        date_group = Adw.PreferencesGroup(title="Due Date")
        date_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                           margin_start=12, margin_end=12, margin_top=8, margin_bottom=8)

        self.date_label = Gtk.Label(
            label=self._selected_date or "No date set",
            hexpand=True, xalign=0,
        )
        date_box.append(self.date_label)

        clear_date_btn = Gtk.Button(icon_name="edit-clear-symbolic", tooltip_text="Clear date")
        clear_date_btn.add_css_class("flat")
        clear_date_btn.connect("clicked", self._on_clear_date)
        date_box.append(clear_date_btn)

        # Calendar popover with MenuButton
        self.calendar = Gtk.Calendar()
        if self._selected_date:
            from gi.repository import GLib
            parts = self._selected_date.split("-")
            dt = GLib.DateTime.new_local(int(parts[0]), int(parts[1]), int(parts[2]), 0, 0, 0)
            self.calendar.select_day(dt)
        self.calendar.connect("day-selected", self._on_day_selected)

        popover = Gtk.Popover(child=self.calendar)
        self.pick_menu_btn = Gtk.MenuButton(
            icon_name="x-office-calendar-symbolic",
            tooltip_text="Pick date",
            popover=popover,
        )
        self.pick_menu_btn.add_css_class("flat")
        date_box.append(self.pick_menu_btn)

        date_group.add(date_box)
        box.append(date_group)

    def _on_day_selected(self, calendar):
        dt = calendar.get_date()
        self._selected_date = "%04d-%02d-%02d" % (dt.get_year(), dt.get_month(), dt.get_day_of_month())
        self.date_label.set_text(self._selected_date)

    def _on_clear_date(self, _btn):
        self._selected_date = None
        self.date_label.set_text("No date set")

    def _on_save(self, _btn):
        title = self.title_row.get_text().strip()
        if not title:
            self.title_row.add_css_class("error")
            return

        buf = self.notes_view.get_buffer()
        notes = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

        cat_idx = self.category_row.get_selected()
        category_id = self.categories[cat_idx - 1].id if cat_idx > 0 else None

        priority = self.priority_row.get_selected()

        task = self.task or Task()
        task.title = title
        task.notes = notes
        task.category_id = category_id
        task.priority = priority
        task.due_date = self._selected_date

        if self.callback:
            self.callback(task)
        self.close()

    def set_callback(self, callback):
        self.callback = callback


class CategoryDialog(Adw.Window):
    """Dialog for adding or editing a category."""

    def __init__(self, parent, category: Category = None):
        super().__init__(
            modal=True,
            transient_for=parent,
            default_width=380,
            default_height=280,
            title="Edit Category" if category else "New Category",
        )
        self.category = category
        self.callback = None
        self._color = category.color if category else "#3584e4"

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)
        toolbar_view.add_top_bar(header)

        clamp = Adw.Clamp(maximum_size=350, margin_top=18, margin_bottom=18,
                          margin_start=12, margin_end=12)
        toolbar_view.set_content(clamp)

        group = Adw.PreferencesGroup()
        clamp.set_child(group)

        # Name
        self.name_row = Adw.EntryRow(title="Category name")
        if category:
            self.name_row.set_text(category.name)
        group.add(self.name_row)

        # Color
        color_row = Adw.ActionRow(title="Color")
        self.color_btn = Gtk.ColorButton()
        rgba = Gdk.RGBA()
        rgba.parse(self._color)
        self.color_btn.set_rgba(rgba)
        self.color_btn.connect("color-set", self._on_color_set)
        color_row.add_suffix(self.color_btn)
        color_row.set_activatable_widget(self.color_btn)
        group.add(color_row)

    def _on_color_set(self, btn):
        rgba = btn.get_rgba()
        self._color = "#%02x%02x%02x" % (
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        )

    def _on_save(self, _btn):
        name = self.name_row.get_text().strip()
        if not name:
            self.name_row.add_css_class("error")
            return

        cat = self.category or Category()
        cat.name = name
        cat.color = self._color

        if self.callback:
            self.callback(cat)
        self.close()

    def set_callback(self, callback):
        self.callback = callback
