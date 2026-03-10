#!/usr/bin/python3
"""Task Manager — a GTK4/libadwaita dashboard-style to-do application."""

import math
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

# ── Constants ───────────────────────────────────────────────────

PRIORITY_COLORS = ["#40c060", "#e88800", "#e04040"]  # Low, Med, High
PRIORITY_LABELS = ["Low", "Med", "High"]
PRIORITY_CSS_BADGE = ["badge-low", "badge-med", "badge-high"]
PRIORITY_CSS_TEXT = ["priority-low", "priority-med", "priority-high"]
WEEK_TASK_CSS = ["week-task-low", "week-task-med", "week-task-high"]

SORT_KEYS = ["priority", "due_date", "title", "created_at"]

FILTER_DASHBOARD = "dashboard"
FILTER_ALL = "all"
FILTER_TODAY = "today"
FILTER_UPCOMING = "upcoming"

SCHEME_NAMES = ["System", "Light", "Dark"]
SCHEME_VALUES = [Adw.ColorScheme.DEFAULT, Adw.ColorScheme.FORCE_LIGHT, Adw.ColorScheme.FORCE_DARK]
SCHEME_STR = ["default", "force_light", "force_dark"]
SCHEME_ICONS = ["weather-clear-symbolic", "display-brightness-symbolic", "weather-clear-night-symbolic"]


# ── Cairo Drawing Helpers ───────────────────────────────────────

def _hex(color):
    return int(color[1:3], 16) / 255, int(color[3:5], 16) / 255, int(color[5:7], 16) / 255


def _fg():
    """Return foreground (r, g, b) based on current theme."""
    dark = Adw.StyleManager.get_default().get_dark()
    return (1, 1, 1) if dark else (0, 0, 0)


def draw_dot(area, cr, w, h):
    r, g, b = _hex(area._color)
    cr.set_source_rgb(r, g, b)
    cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 2 * math.pi)
    cr.fill()


def draw_color_bar(area, cr, w, h):
    r, g, b = _hex(area._color)
    cr.set_source_rgb(r, g, b)
    radius = min(w, 3)
    cr.move_to(radius, 0)
    cr.line_to(w, 0)
    cr.line_to(w, h)
    cr.line_to(radius, h)
    cr.arc(radius, h - radius, radius, math.pi / 2, math.pi)
    cr.line_to(0, radius)
    cr.arc(radius, radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()
    cr.fill()


def draw_progress_ring(area, cr, w, h):
    pct = area._pct
    fg = _fg()
    cx, cy = w / 2, h / 2
    radius = min(cx, cy) - 8
    lw = 10
    # Background ring
    cr.set_source_rgba(*fg, 0.08)
    cr.set_line_width(lw)
    cr.arc(cx, cy, radius, 0, 2 * math.pi)
    cr.stroke()
    # Progress arc
    if pct > 0:
        cr.set_source_rgba(0.27, 0.53, 1.0, 0.9)
        cr.set_line_width(lw)
        cr.set_line_cap(1)  # ROUND
        start = -math.pi / 2
        end = start + (pct / 100) * 2 * math.pi
        cr.arc(cx, cy, radius, start, end)
        cr.stroke()
    # Center text
    cr.set_source_rgba(*fg, 0.9)
    cr.select_font_face("Sans", 0, 1)
    cr.set_font_size(26)
    text = f"{pct}%"
    ext = cr.text_extents(text)
    cr.move_to(cx - ext.width / 2, cy + ext.height / 2)
    cr.show_text(text)


def draw_bar_chart(area, cr, w, h):
    fg = _fg()
    data = area._data
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    vals = [data.get(d, 0) for d in days]
    mx = max(vals) if any(vals) else 1
    mx = max(mx, 1)
    n = len(days)
    sw = w / n
    bw = sw * 0.45
    ch = h - 22

    for i, (d, v) in enumerate(zip(days, vals)):
        x = i * sw + (sw - bw) / 2
        # Bg slot
        cr.set_source_rgba(*fg, 0.04)
        cr.rectangle(x, 0, bw, ch)
        cr.fill()
        # Bar
        if v > 0:
            bh = (v / mx) * ch
            y = ch - bh
            cr.set_source_rgba(0.27, 0.53, 1.0, 0.8)
            r = min(3, bw / 2)
            cr.move_to(x, ch)
            cr.line_to(x, y + r)
            cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
            cr.arc(x + bw - r, y + r, r, 1.5 * math.pi, 0)
            cr.line_to(x + bw, ch)
            cr.close_path()
            cr.fill()
        # Label
        cr.set_source_rgba(*fg, 0.35)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(8)
        ext = cr.text_extents(d)
        cr.move_to(x + bw / 2 - ext.width / 2, h - 5)
        cr.show_text(d)


def draw_donut(area, cr, w, h):
    fg = _fg()
    data = area._data  # [(name, color, count), ...]
    total = sum(d[2] for d in data)
    cx, cy = w / 2, h / 2
    outer = min(cx, cy) - 6
    inner = outer * 0.62
    gap = 0.03

    if total == 0:
        cr.set_source_rgba(*fg, 0.08)
        cr.set_line_width(outer - inner)
        cr.arc(cx, cy, (outer + inner) / 2, 0, 2 * math.pi)
        cr.stroke()
    else:
        angle = -math.pi / 2
        for _, col, cnt in data:
            if cnt == 0:
                continue
            sweep = (cnt / total) * 2 * math.pi - gap
            if sweep <= 0:
                angle += gap
                continue
            r, g, b = _hex(col)
            cr.set_source_rgb(r, g, b)
            cr.arc(cx, cy, outer, angle, angle + sweep)
            cr.arc_negative(cx, cy, inner, angle + sweep, angle)
            cr.close_path()
            cr.fill()
            angle += sweep + gap

    # Center text
    cr.set_source_rgba(*fg, 0.9)
    cr.select_font_face("Sans", 0, 1)
    cr.set_font_size(20)
    t = str(total)
    ext = cr.text_extents(t)
    cr.move_to(cx - ext.width / 2, cy + 3)
    cr.show_text(t)
    cr.set_font_size(8)
    cr.set_source_rgba(*fg, 0.45)
    t2 = "tasks"
    ext2 = cr.text_extents(t2)
    cr.move_to(cx - ext2.width / 2, cy + 16)
    cr.show_text(t2)


# ── TaskRow (for list view) ─────────────────────────────────────

class TaskRow(Gtk.ListBoxRow):

    def __init__(self, task, cat_color, on_toggle, on_edit, on_delete):
        super().__init__()
        self.task = task
        self.add_css_class("task-row")

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                       margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        self.set_child(hbox)

        if cat_color:
            bar = Gtk.DrawingArea(content_width=4, content_height=36, valign=Gtk.Align.CENTER)
            bar._color = cat_color
            bar.set_draw_func(draw_color_bar)
            hbox.append(bar)

        check = Gtk.CheckButton(active=task.completed, valign=Gtk.Align.CENTER)
        check.connect("toggled", lambda _: on_toggle(task))
        hbox.append(check)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True,
                       valign=Gtk.Align.CENTER)
        hbox.append(vbox)
        title = Gtk.Label(label=task.title, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("task-title")
        vbox.append(title)
        if task.notes:
            sub = Gtk.Label(label=task.notes.replace("\n", " ")[:80], xalign=0,
                            ellipsize=Pango.EllipsizeMode.END)
            sub.add_css_class("task-subtitle")
            sub.add_css_class("dim-label")
            vbox.append(sub)

        badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
        hbox.append(badges)
        if task.due_date:
            badges.append(self._due_badge(task.due_date, task.completed))
        pri = Gtk.Label(label=PRIORITY_LABELS[task.priority])
        pri.add_css_class("priority-badge")
        pri.add_css_class(PRIORITY_CSS_BADGE[task.priority])
        badges.append(pri)

        acts = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, valign=Gtk.Align.CENTER)
        acts.add_css_class("task-actions")
        hbox.append(acts)
        eb = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit")
        eb.add_css_class("flat")
        eb.connect("clicked", lambda _: on_edit(task))
        acts.append(eb)
        db = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete")
        db.add_css_class("flat")
        db.add_css_class("delete-btn")
        db.connect("clicked", lambda _: on_delete(task))
        acts.append(db)

        if task.completed:
            self.add_css_class("task-completed")

    def _due_badge(self, due_str, done):
        lbl = Gtk.Label()
        lbl.add_css_class("due-badge")
        today = date.today()
        try:
            d = date.fromisoformat(due_str)
        except ValueError:
            lbl.set_label(due_str)
            return lbl
        if done:
            lbl.set_label(due_str)
        elif d < today:
            lbl.set_label(f"{(today - d).days}d overdue")
            lbl.add_css_class("overdue")
        elif d == today:
            lbl.set_label("Today")
            lbl.add_css_class("due-today")
        elif d == today + timedelta(days=1):
            lbl.set_label("Tomorrow")
        else:
            lbl.set_label(due_str)
        return lbl


# ── Main Window ─────────────────────────────────────────────────

class TaskManagerWindow(Adw.ApplicationWindow):

    def __init__(self, **kwargs):
        super().__init__(default_width=1200, default_height=720, **kwargs)
        self.db = Database()
        self.current_filter = FILTER_DASHBOARD
        self.current_category_id = None
        self.current_sort = "priority"
        self.show_completed = True
        self._cat_colors = {}

        self._build_ui()
        self._load_theme()
        self.refresh_all()

    def _load_theme(self):
        saved = self.db.get_setting("color_scheme", "default")
        idx = SCHEME_STR.index(saved) if saved in SCHEME_STR else 2
        Adw.StyleManager.get_default().set_color_scheme(SCHEME_VALUES[idx])
        self._theme_loading = True
        self.theme_btns[idx].set_active(True)
        self._theme_loading = False

    # ── UI Build ────────────────────────────────────────────────

    def _build_ui(self):
        toolbar = Adw.ToolbarView()
        self.set_content(toolbar)

        # Header bar
        header = Adw.HeaderBar()
        title = Gtk.Label(label="Task Manager")
        title.add_css_class("app-title")
        header.set_title_widget(title)

        add_btn = Gtk.Button(tooltip_text="Add Task")
        add_btn.add_css_class("suggested-action")
        add_btn.add_css_class("add-task-btn")
        ab = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        ab.append(Gtk.Image(icon_name="list-add-symbolic"))
        ab.append(Gtk.Label(label="Add Task"))
        add_btn.set_child(ab)
        add_btn.connect("clicked", self._on_add_task)
        header.pack_start(add_btn)

        rbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        header.pack_end(rbox)
        self.comp_toggle = Gtk.ToggleButton(icon_name="object-select-symbolic",
                                            tooltip_text="Show/hide completed", active=True)
        self.comp_toggle.connect("toggled", self._on_toggle_completed)
        rbox.append(self.comp_toggle)
        sm = Gtk.StringList.new(["Priority", "Due Date", "A-Z", "Date Added"])
        self.sort_dd = Gtk.DropDown(model=sm, tooltip_text="Sort by")
        self.sort_dd.connect("notify::selected", self._on_sort_changed)
        rbox.append(self.sort_dd)
        toolbar.add_top_bar(header)

        # Three-column layout
        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        toolbar.set_content(columns)

        # 1. Sidebar
        columns.append(self._build_sidebar())
        columns.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # 2. Content stack (dashboard / task list)
        self.content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                                       hexpand=True)
        self.content_stack.add_named(self._build_dashboard(), "dashboard")
        self.content_stack.add_named(self._build_task_list(), "tasks")
        columns.append(self.content_stack)

        # 3. Stats panel
        columns.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        columns.append(self._build_stats_panel())

    # ── Sidebar ─────────────────────────────────────────────────

    def _build_sidebar(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                      width_request=230)
        box.add_css_class("sidebar")

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        box.append(scroll)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                        margin_top=8, margin_bottom=8)
        scroll.set_child(inner)

        # Navigation
        lbl = Gtk.Label(label="NAVIGATION", xalign=0, margin_start=16, margin_top=8, margin_bottom=4)
        lbl.add_css_class("sidebar-section-title")
        inner.append(lbl)

        self.count_labels = {}
        self.nav_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav_listbox.add_css_class("navigation-sidebar")
        self.nav_listbox.connect("row-selected", self._on_nav_selected)
        inner.append(self.nav_listbox)

        self._add_nav_row("Dashboard", FILTER_DASHBOARD, "view-grid-symbolic")
        self._add_nav_row("All Tasks", FILTER_ALL, "view-list-symbolic")
        self._add_nav_row("Today", FILTER_TODAY, "alarm-symbolic")
        self._add_nav_row("Upcoming", FILTER_UPCOMING, "x-office-calendar-symbolic")

        sep = Gtk.Separator(margin_top=10, margin_bottom=6)
        sep.add_css_class("sidebar-separator")
        inner.append(sep)

        # Categories
        ch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                     margin_start=16, margin_end=8, margin_bottom=4)
        cl = Gtk.Label(label="CATEGORIES", xalign=0, hexpand=True)
        cl.add_css_class("sidebar-section-title")
        ch.append(cl)
        ab = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add category")
        ab.add_css_class("flat")
        ab.connect("clicked", self._on_add_category)
        ch.append(ab)
        inner.append(ch)

        self.cat_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.cat_listbox.add_css_class("navigation-sidebar")
        self.cat_listbox.connect("row-selected", self._on_cat_selected)
        inner.append(self.cat_listbox)

        sep2 = Gtk.Separator(margin_top=10, margin_bottom=6)
        sep2.add_css_class("sidebar-separator")
        inner.append(sep2)

        # Theme
        tl = Gtk.Label(label="APPEARANCE", xalign=0, margin_start=16, margin_bottom=6)
        tl.add_css_class("sidebar-section-title")
        inner.append(tl)

        tbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                       margin_start=12, margin_end=12, margin_bottom=12,
                       halign=Gtk.Align.CENTER, homogeneous=True)
        tbox.add_css_class("linked")
        inner.append(tbox)

        self.theme_btns = []
        for i, name in enumerate(SCHEME_NAMES):
            b = Gtk.ToggleButton(tooltip_text=name)
            bx = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, halign=Gtk.Align.CENTER)
            bx.append(Gtk.Image(icon_name=SCHEME_ICONS[i]))
            bx.append(Gtk.Label(label=name))
            b.set_child(bx)
            b.add_css_class("theme-btn")
            b.connect("toggled", self._on_theme, i)
            tbox.append(b)
            self.theme_btns.append(b)

        return box

    def _add_nav_row(self, text, fid, icon):
        row = Gtk.ListBoxRow()
        row.filter_id = fid
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                     margin_start=10, margin_end=10, margin_top=5, margin_bottom=5)
        hb.append(Gtk.Image(icon_name=icon))
        hb.append(Gtk.Label(label=text, xalign=0, hexpand=True))
        cl = Gtk.Label(label="0")
        cl.add_css_class("count-badge")
        cl.add_css_class("count-badge-zero")
        self.count_labels[fid] = cl
        hb.append(cl)
        row.set_child(hb)
        self.nav_listbox.append(row)

    # ── Dashboard View ──────────────────────────────────────────

    def _build_dashboard(self):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.dash_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                                margin_top=20, margin_bottom=20, margin_start=20, margin_end=20)
        scroll.set_child(self.dash_box)
        return scroll

    def refresh_dashboard(self):
        _clear(self.dash_box)
        today_str = date.today().isoformat()
        week_later = (date.today() + timedelta(days=7)).isoformat()

        all_active = self.db.get_tasks(show_completed=False, sort_by="priority")
        today_tasks = [t for t in all_active if t.due_date == today_str]
        upcoming = [t for t in all_active if t.due_date and today_str <= t.due_date <= week_later]

        # Top row: Today's Tasks + Upcoming
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16, homogeneous=True)
        self.dash_box.append(top)
        top.append(self._card_today(today_tasks))
        top.append(self._card_upcoming(upcoming))

        # Week view
        self.dash_box.append(self._card_week())

    def _card_today(self, tasks):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("dashboard-card")
        # Header
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        card.append(hdr)
        hdr.append(Gtk.Label(label="Today's Tasks", xalign=0, hexpand=True, css_classes=["card-title"]))
        badge = Gtk.Label(label=str(len(tasks)))
        badge.add_css_class("count-badge")
        if len(tasks) == 0:
            badge.add_css_class("count-badge-zero")
        hdr.append(badge)
        btn = Gtk.Button(label="View All →")
        btn.add_css_class("flat")
        btn.add_css_class("card-action")
        btn.connect("clicked", lambda _: self._nav_to(FILTER_TODAY))
        hdr.append(btn)

        if not tasks:
            e = Gtk.Label(label="No tasks due today", margin_top=16, margin_bottom=16)
            e.add_css_class("dim-label")
            card.append(e)
        else:
            for t in tasks[:5]:
                card.append(self._dash_task_item(t))
            if len(tasks) > 5:
                card.append(Gtk.Label(label=f"+{len(tasks)-5} more", css_classes=["dim-label"],
                                      margin_top=4))
        return card

    def _card_upcoming(self, tasks):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("dashboard-card")
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        card.append(hdr)
        hdr.append(Gtk.Label(label="Upcoming", xalign=0, hexpand=True, css_classes=["card-title"]))
        badge = Gtk.Label(label=str(len(tasks)))
        badge.add_css_class("count-badge")
        if len(tasks) == 0:
            badge.add_css_class("count-badge-zero")
        hdr.append(badge)
        btn = Gtk.Button(label="View All →")
        btn.add_css_class("flat")
        btn.add_css_class("card-action")
        btn.connect("clicked", lambda _: self._nav_to(FILTER_UPCOMING))
        hdr.append(btn)

        if not tasks:
            e = Gtk.Label(label="No upcoming tasks this week", margin_top=16, margin_bottom=16)
            e.add_css_class("dim-label")
            card.append(e)
        else:
            for t in tasks[:5]:
                card.append(self._dash_task_item(t))
            if len(tasks) > 5:
                card.append(Gtk.Label(label=f"+{len(tasks)-5} more", css_classes=["dim-label"],
                                      margin_top=4))
        return card

    def _dash_task_item(self, task):
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hb.add_css_class("task-item")
        if task.completed:
            hb.add_css_class("task-item-completed")

        # Priority dot
        dot = Gtk.DrawingArea(content_width=10, content_height=10, valign=Gtk.Align.CENTER)
        dot._color = PRIORITY_COLORS[task.priority]
        dot.set_draw_func(draw_dot)
        hb.append(dot)

        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
        hb.append(vb)
        tl = Gtk.Label(label=task.title, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        tl.add_css_class("task-item-title")
        vb.append(tl)
        if task.notes:
            dl = Gtk.Label(label=task.notes.replace("\n", " ")[:50], xalign=0,
                           ellipsize=Pango.EllipsizeMode.END)
            dl.add_css_class("task-item-desc")
            vb.append(dl)

        # Checkbox
        ck = Gtk.CheckButton(active=task.completed, valign=Gtk.Align.CENTER)
        ck.connect("toggled", lambda _: self._on_task_toggled(task))
        hb.append(ck)
        return hb

    def _card_week(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("dashboard-card")
        card.append(Gtk.Label(label="This Week", xalign=0, css_classes=["card-title"]))

        week = self.db.get_week_tasks()
        today_str = date.today().isoformat()

        cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
        card.append(cols)

        for label, d_str, tasks in week:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            col.add_css_class("week-day-col")
            if d_str == today_str:
                col.add_css_class("week-day-today")

            hl = Gtk.Label(label=label)
            hl.add_css_class("week-day-header")
            if d_str == today_str:
                hl.add_css_class("week-day-header-today")
            col.append(hl)

            if not tasks:
                el = Gtk.Label(label="—")
                el.add_css_class("week-empty")
                col.append(el)
            else:
                for t in tasks[:3]:
                    tc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                    tc.add_css_class("week-task-card")
                    tc.add_css_class(WEEK_TASK_CSS[t.priority])

                    ph = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                    d = Gtk.DrawingArea(content_width=8, content_height=8, valign=Gtk.Align.CENTER)
                    d._color = PRIORITY_COLORS[t.priority]
                    d.set_draw_func(draw_dot)
                    ph.append(d)
                    pl = Gtk.Label(label=PRIORITY_LABELS[t.priority])
                    pl.add_css_class("week-task-priority")
                    pl.add_css_class(PRIORITY_CSS_TEXT[t.priority])
                    ph.append(pl)
                    tc.append(ph)

                    ttl = Gtk.Label(label=t.title, xalign=0, ellipsize=Pango.EllipsizeMode.END,
                                    max_width_chars=18)
                    ttl.add_css_class("week-task-title")
                    tc.append(ttl)

                    if t.notes:
                        desc = Gtk.Label(label=t.notes.replace("\n", " ")[:35], xalign=0,
                                         ellipsize=Pango.EllipsizeMode.END, max_width_chars=18)
                        desc.add_css_class("week-task-desc")
                        tc.append(desc)

                    col.append(tc)

                if len(tasks) > 3:
                    col.append(Gtk.Label(label=f"+{len(tasks)-3}", css_classes=["dim-label"]))

            cols.append(col)

        return card

    # ── Task List View ──────────────────────────────────────────

    def _build_task_list(self):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=750, margin_top=12, margin_bottom=12)
        scroll.set_child(clamp)

        self.tl_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        clamp.set_child(self.tl_stack)

        self.task_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.task_listbox.add_css_class("boxed-list")
        self.tl_stack.add_named(self.task_listbox, "list")

        empty = Adw.StatusPage(icon_name="checkbox-checked-symbolic",
                               title="No Tasks",
                               description='Click "Add Task" to get started')
        empty.add_css_class("empty-state")
        self.tl_stack.add_named(empty, "empty")
        return scroll

    def refresh_task_list(self):
        _clear(self.task_listbox)
        tasks = self.db.get_tasks(category_id=self.current_category_id,
                                  show_completed=self.show_completed,
                                  sort_by=self.current_sort)

        if self.current_filter == FILTER_TODAY:
            ts = date.today().isoformat()
            tasks = [t for t in tasks if t.due_date == ts]
        elif self.current_filter == FILTER_UPCOMING:
            ts = date.today().isoformat()
            wl = (date.today() + timedelta(days=7)).isoformat()
            tasks = [t for t in tasks if t.due_date and ts <= t.due_date <= wl]

        if not tasks:
            self.tl_stack.set_visible_child_name("empty")
        else:
            self.tl_stack.set_visible_child_name("list")
            for t in tasks:
                self.task_listbox.append(
                    TaskRow(t, self._cat_colors.get(t.category_id),
                            self._on_task_toggled, self._on_edit_task, self._on_delete_task))

    # ── Stats Panel ─────────────────────────────────────────────

    def _build_stats_panel(self):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    width_request=300)
        scroll.add_css_class("stats-panel")
        self.stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                                 margin_top=20, margin_bottom=20, margin_start=16, margin_end=16)
        scroll.set_child(self.stats_box)
        return scroll

    def refresh_stats(self):
        _clear(self.stats_box)
        self.stats_box.append(self._stats_activity())
        self.stats_box.append(self._stats_categories())
        self.stats_box.append(self._stats_reminders())

    def _stats_activity(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("dashboard-card")

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.append(Gtk.Label(label="Activity", xalign=0, hexpand=True, css_classes=["card-title"]))
        comp, total = self.db.get_completion_rate()
        if total > 0:
            badge = Gtk.Label(label=f"+{comp}")
            badge.add_css_class("stat-trend-up")
            hdr.append(badge)
        card.append(hdr)

        # Progress ring
        pct = int(comp / total * 100) if total > 0 else 0
        ring = Gtk.DrawingArea(content_width=130, content_height=130, halign=Gtk.Align.CENTER)
        ring._pct = pct
        ring.set_draw_func(draw_progress_ring)
        card.append(ring)

        # Weekly bar chart
        weekly = self.db.get_weekly_completions()
        bars = Gtk.DrawingArea(content_width=250, content_height=90)
        bars._data = weekly
        bars.set_draw_func(draw_bar_chart)
        card.append(bars)
        return card

    def _stats_categories(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("dashboard-card")

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.append(Gtk.Label(label="Projects", xalign=0, hexpand=True, css_classes=["card-title"]))
        card.append(hdr)

        stats = self.db.get_category_stats()
        if not stats:
            card.append(Gtk.Label(label="No active tasks", css_classes=["dim-label"],
                                  margin_top=12, margin_bottom=12))
            return card

        # Donut
        donut = Gtk.DrawingArea(content_width=140, content_height=140, halign=Gtk.Align.CENTER)
        donut._data = stats
        donut.set_draw_func(draw_donut)
        card.append(donut)

        # Legend
        total = sum(s[2] for s in stats) or 1
        for name, col, cnt in stats:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          margin_top=3, margin_bottom=3)
            dot = Gtk.DrawingArea(content_width=10, content_height=10, valign=Gtk.Align.CENTER)
            dot._color = col
            dot.set_draw_func(draw_dot)
            row.append(dot)
            row.append(Gtk.Label(label=name, xalign=0, hexpand=True, css_classes=["legend-name"]))
            row.append(Gtk.Label(label=f"{int(cnt/total*100)}%", css_classes=["legend-pct"]))
            card.append(row)
        return card

    def _stats_reminders(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("dashboard-card")

        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hdr.append(Gtk.Label(label="Reminders", xalign=0, hexpand=True, css_classes=["card-title"]))
        btn = Gtk.Button(label="Manage →")
        btn.add_css_class("flat")
        btn.add_css_class("card-action")
        btn.connect("clicked", lambda _: self._nav_to(FILTER_ALL))
        hdr.append(btn)
        card.append(hdr)

        reminders = self.db.get_reminders(limit=4)
        if not reminders:
            card.append(Gtk.Label(label="No upcoming tasks", css_classes=["dim-label"],
                                  margin_top=12, margin_bottom=12))
            return card

        today = date.today()
        for t in reminders:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.add_css_class("reminder-row")

            # Date column
            try:
                d = date.fromisoformat(t.due_date)
                if d == today:
                    main_text, sub_text = "Today", ""
                elif d == today + timedelta(days=1):
                    main_text, sub_text = "Tomorrow", ""
                else:
                    main_text = str(d.day)
                    sub_text = d.strftime("%b")
            except ValueError:
                main_text, sub_text = t.due_date or "?", ""

            dbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                           width_request=50)
            dbox.append(Gtk.Label(label=main_text, css_classes=["reminder-date"]))
            if sub_text:
                dbox.append(Gtk.Label(label=sub_text, css_classes=["reminder-date-sub"]))
            row.append(dbox)

            # Title
            row.append(Gtk.Label(label=t.title, xalign=0, hexpand=True,
                                 ellipsize=Pango.EllipsizeMode.END, css_classes=["reminder-title"]))

            # Priority
            pbadge = Gtk.Label(label=PRIORITY_LABELS[t.priority])
            pbadge.add_css_class("priority-badge")
            pbadge.add_css_class(PRIORITY_CSS_BADGE[t.priority])
            row.append(pbadge)

            card.append(row)
        return card

    # ── Refresh All ─────────────────────────────────────────────

    def refresh_all(self):
        self.refresh_sidebar()
        if self.current_filter == FILTER_DASHBOARD:
            self.content_stack.set_visible_child_name("dashboard")
            self.refresh_dashboard()
        else:
            self.content_stack.set_visible_child_name("tasks")
            self.refresh_task_list()
        self.refresh_stats()

    def refresh_sidebar(self):
        _clear(self.cat_listbox)
        cats = self.db.get_categories()
        counts = self.db.get_task_counts()
        self._cat_colors = {c.id: c.color for c in cats}

        for cat in cats:
            row = Gtk.ListBoxRow()
            row.category_id = cat.id
            row.category_name = cat.name
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                         margin_start=10, margin_end=10, margin_top=5, margin_bottom=5)
            dot = Gtk.DrawingArea(content_width=12, content_height=12, valign=Gtk.Align.CENTER)
            dot._color = cat.color
            dot.set_draw_func(draw_dot)
            hb.append(dot)
            hb.append(Gtk.Label(label=cat.name, xalign=0, hexpand=True))
            c = counts.get(cat.id, 0)
            cl = Gtk.Label(label=str(c))
            cl.add_css_class("count-badge")
            if c == 0:
                cl.add_css_class("count-badge-zero")
            hb.append(cl)
            row.set_child(hb)

            g = Gtk.GestureClick(button=3)
            g.connect("pressed", self._on_cat_rclick, cat)
            row.add_controller(g)
            self.cat_listbox.append(row)

        # Update nav counts
        all_c = counts.get("all", 0)
        self._set_count(FILTER_ALL, all_c)

        ts = date.today().isoformat()
        active = self.db.get_tasks(show_completed=False)
        self._set_count(FILTER_TODAY, sum(1 for t in active if t.due_date == ts))
        wl = (date.today() + timedelta(days=7)).isoformat()
        self._set_count(FILTER_UPCOMING,
                        sum(1 for t in active if t.due_date and ts <= t.due_date <= wl))
        self._set_count(FILTER_DASHBOARD, all_c)

    def _set_count(self, fid, n):
        lbl = self.count_labels.get(fid)
        if not lbl:
            return
        lbl.set_label(str(n))
        if n == 0:
            lbl.add_css_class("count-badge-zero")
        else:
            lbl.remove_css_class("count-badge-zero")

    # ── Navigation ──────────────────────────────────────────────

    def _on_nav_selected(self, lb, row):
        if row is None:
            return
        self.cat_listbox.select_row(None)
        self.current_filter = row.filter_id
        self.current_category_id = None
        if self.current_filter == FILTER_DASHBOARD:
            self.content_stack.set_visible_child_name("dashboard")
            self.refresh_dashboard()
        else:
            self.content_stack.set_visible_child_name("tasks")
            self.refresh_task_list()

    def _on_cat_selected(self, lb, row):
        if row is None:
            return
        self.nav_listbox.select_row(None)
        self.current_filter = "category"
        self.current_category_id = row.category_id
        self.content_stack.set_visible_child_name("tasks")
        self.refresh_task_list()

    def _nav_to(self, fid):
        for i in range(10):
            r = self.nav_listbox.get_row_at_index(i)
            if r is None:
                break
            if hasattr(r, "filter_id") and r.filter_id == fid:
                self.nav_listbox.select_row(r)
                break

    # ── Theme ───────────────────────────────────────────────────

    def _on_theme(self, btn, idx):
        if getattr(self, "_theme_loading", False):
            return
        if not btn.get_active():
            return
        self._theme_loading = True
        for i, b in enumerate(self.theme_btns):
            if i != idx:
                b.set_active(False)
        self._theme_loading = False
        Adw.StyleManager.get_default().set_color_scheme(SCHEME_VALUES[idx])
        self.db.set_setting("color_scheme", SCHEME_STR[idx])
        # Redraw charts with updated foreground colors
        self.refresh_all()

    # ── Task CRUD ───────────────────────────────────────────────

    def _on_add_task(self, _btn):
        cats = self.db.get_categories()
        dlg = TaskDialog(self, cats, default_category_id=self.current_category_id)
        dlg.set_callback(lambda t: (self.db.add_task(t), self.refresh_all()))
        dlg.present()

    def _on_edit_task(self, task):
        cats = self.db.get_categories()
        dlg = TaskDialog(self, cats, task=task)
        dlg.set_callback(lambda t: (self.db.update_task(t), self.refresh_all()))
        dlg.present()

    def _on_delete_task(self, task):
        d = Adw.MessageDialog(heading="Delete Task?",
                              body=f'Delete "{task.title}"?', transient_for=self)
        d.add_response("cancel", "Cancel")
        d.add_response("delete", "Delete")
        d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _, r: (self.db.delete_task(task.id), self.refresh_all())
                  if r == "delete" else None)
        d.present()

    def _on_task_toggled(self, task):
        self.db.toggle_task(task.id)
        self.refresh_all()

    # ── Category CRUD ───────────────────────────────────────────

    def _on_add_category(self, _btn):
        dlg = CategoryDialog(self)
        dlg.set_callback(lambda c: (self.db.add_category(c), self.refresh_all()))
        dlg.present()

    def _on_cat_rclick(self, gesture, _n, x, y, cat):
        menu = Gio.Menu()
        menu.append("Edit", f"cat.edit-{cat.id}")
        menu.append("Delete", f"cat.delete-{cat.id}")
        ag = Gio.SimpleActionGroup()
        ea = Gio.SimpleAction(name=f"edit-{cat.id}")
        ea.connect("activate", lambda *_: self._edit_cat(cat))
        ag.add_action(ea)
        da = Gio.SimpleAction(name=f"delete-{cat.id}")
        da.connect("activate", lambda *_: self._del_cat(cat))
        ag.add_action(da)
        row = gesture.get_widget()
        row.insert_action_group("cat", ag)
        p = Gtk.PopoverMenu(menu_model=menu, has_arrow=True)
        p.set_parent(row)
        p.popup()

    def _edit_cat(self, cat):
        dlg = CategoryDialog(self, category=cat)
        dlg.set_callback(lambda c: (self.db.update_category(c), self.refresh_all()))
        dlg.present()

    def _del_cat(self, cat):
        d = Adw.MessageDialog(heading="Delete Category?",
                              body=f'Delete "{cat.name}"? Tasks become uncategorized.',
                              transient_for=self)
        d.add_response("cancel", "Cancel")
        d.add_response("delete", "Delete")
        d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_resp(_, r):
            if r == "delete":
                self.db.delete_category(cat.id)
                self.current_filter = FILTER_DASHBOARD
                self.current_category_id = None
                self.nav_listbox.select_row(self.nav_listbox.get_row_at_index(0))
                self.refresh_all()

        d.connect("response", on_resp)
        d.present()

    # ── Sort & Filter ───────────────────────────────────────────

    def _on_sort_changed(self, dd, _):
        self.current_sort = SORT_KEYS[dd.get_selected()]
        if self.current_filter != FILTER_DASHBOARD:
            self.refresh_task_list()

    def _on_toggle_completed(self, btn):
        self.show_completed = btn.get_active()
        if self.current_filter != FILTER_DASHBOARD:
            self.refresh_task_list()


# ── Helpers ─────────────────────────────────────────────────────

def _clear(widget):
    while True:
        child = widget.get_first_child()
        if child is None:
            break
        widget.remove(child)


# ── Application ─────────────────────────────────────────────────

class TaskManagerApp(Adw.Application):

    def __init__(self):
        super().__init__(application_id="com.lab7.taskmanager",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Apply theme early
        db = Database()
        saved = db.get_setting("color_scheme", "default")
        idx = SCHEME_STR.index(saved) if saved in SCHEME_STR else 2
        Adw.StyleManager.get_default().set_color_scheme(SCHEME_VALUES[idx])
        # CSS
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        win = TaskManagerWindow(application=self)
        win.present()


def main():
    app = TaskManagerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
