#!/usr/bin/python3
"""Waterfall / Gantt chart view with drag-to-reorder, today marker, and polished visuals."""

import math
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Pango

from database import Database
from models import Phase, Project

STATUS_LABELS = ["Not Started", "In Progress", "Completed"]
STATUS_COLORS = ["#888888", "#4488ff", "#1e8e3e"]

ROW_H = 52
HEADER_H = 56
NAME_W = 200
DRAG_THRESHOLD = 8


def _hex(c):
    return int(c[1:3], 16) / 255, int(c[3:5], 16) / 255, int(c[5:7], 16) / 255


def _fg():
    dark = Adw.StyleManager.get_default().get_dark()
    return (1, 1, 1) if dark else (0, 0, 0)


def _is_dark():
    return Adw.StyleManager.get_default().get_dark()


def _rounded_rect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.move_to(x + r, y)
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class WaterfallView(Gtk.Box):

    def __init__(self, db: Database, on_change=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.db = db
        self.on_change = on_change
        self.project_id = None
        self.project_name = ""
        self.phases = []
        self.selected_idx = -1

        # Drag state
        self._drag_idx = -1
        self._drag_active = False
        self._drag_offset_y = 0
        self._drag_cur_y = 0
        self._drop_idx = -1

        # Hover state
        self._hover_idx = -1

        # ── Toolbar ──────────────────────────────────────────────
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                     margin_start=16, margin_end=16, margin_top=10, margin_bottom=6)
        tb.add_css_class("view-toolbar")
        self.append(tb)

        self.title_label = Gtk.Label(label="Project", xalign=0, hexpand=True)
        self.title_label.add_css_class("card-title")
        tb.append(self.title_label)

        self.up_btn = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Move Up", sensitive=False)
        self.up_btn.add_css_class("flat")
        self.up_btn.connect("clicked", self._on_move_up)
        tb.append(self.up_btn)

        self.down_btn = Gtk.Button(icon_name="go-down-symbolic", tooltip_text="Move Down", sensitive=False)
        self.down_btn.add_css_class("flat")
        self.down_btn.connect("clicked", self._on_move_down)
        tb.append(self.down_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        tb.append(sep)

        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Phase")
        add_btn.add_css_class("flat")
        add_btn.connect("clicked", self._on_add)
        tb.append(add_btn)

        self.edit_btn = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit", sensitive=False)
        self.edit_btn.add_css_class("flat")
        self.edit_btn.connect("clicked", self._on_edit)
        tb.append(self.edit_btn)

        self.del_btn = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete", sensitive=False)
        self.del_btn.add_css_class("flat")
        self.del_btn.connect("clicked", self._on_delete)
        tb.append(self.del_btn)

        # Legend
        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16,
                         margin_start=16, margin_bottom=6)
        self.append(legend)
        for i, name in enumerate(STATUS_LABELS):
            lb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            dot = Gtk.DrawingArea(content_width=10, content_height=10, valign=Gtk.Align.CENTER)
            dot._color = STATUS_COLORS[i]
            dot.set_draw_func(lambda a, cr, w, h: (
                cr.set_source_rgb(*_hex(a._color)),
                cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 2 * math.pi),
                cr.fill()))
            lb.append(dot)
            lb.append(Gtk.Label(label=name, css_classes=["dim-label"]))
            legend.append(lb)

        # Chart area
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.append(scroll)
        self.canvas = Gtk.DrawingArea()
        self.canvas.set_draw_func(self._draw)
        scroll.set_child(self.canvas)

        # Click gesture
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._on_click)
        self.canvas.add_controller(click)

        # Drag gesture for reordering
        drag = Gtk.GestureDrag(button=1)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.canvas.add_controller(drag)

        # Motion for hover
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.canvas.add_controller(motion)

    def load(self, project_id: int, project_name: str):
        self.project_id = project_id
        self.project_name = project_name
        self.title_label.set_label(f"Project: {project_name}")
        self.selected_idx = -1
        self._hover_idx = -1
        self._refresh()

    def _refresh(self):
        self.phases = self.db.get_phases(self.project_id) if self.project_id else []
        h = HEADER_H + max(len(self.phases), 1) * ROW_H + 40
        self.canvas.set_content_height(max(h, 300))
        self.canvas.set_content_width(950)
        self.canvas.queue_draw()
        self._update_buttons()

    def _update_buttons(self):
        sel = 0 <= self.selected_idx < len(self.phases)
        self.edit_btn.set_sensitive(sel)
        self.del_btn.set_sensitive(sel)
        self.up_btn.set_sensitive(sel and self.selected_idx > 0)
        self.down_btn.set_sensitive(sel and self.selected_idx < len(self.phases) - 1)

    # ── Drawing ──────────────────────────────────────────────────

    def _draw(self, area, cr, w, h):
        dark = _is_dark()
        fg = _fg()
        phases = self.phases

        if not phases:
            self._draw_empty_state(cr, w, h, fg, dark)
            return

        # Collect dates
        all_dates = []
        for p in phases:
            try:
                all_dates.append(date.fromisoformat(p.start_date))
                all_dates.append(date.fromisoformat(p.end_date))
            except ValueError:
                pass
        if not all_dates:
            return

        min_d = min(all_dates) - timedelta(days=5)
        max_d = max(all_dates) + timedelta(days=5)
        total = (max_d - min_d).days or 1

        chart_l = NAME_W + 20
        chart_w = w - chart_l - 20

        def date_to_x(d):
            return chart_l + ((d - min_d).days / total) * chart_w

        # Draw month grid lines
        cr.set_source_rgba(*fg, 0.06)
        d = min_d.replace(day=1)
        while d <= max_d:
            if d >= min_d:
                x = date_to_x(d)
                cr.set_line_width(1)
                cr.move_to(x, HEADER_H - 20)
                cr.line_to(x, HEADER_H + len(phases) * ROW_H)
                cr.stroke()
                # Month label
                cr.set_source_rgba(*fg, 0.3)
                cr.select_font_face("Sans", 0, 0)
                cr.set_font_size(10)
                cr.move_to(x + 4, HEADER_H - 8)
                cr.show_text(d.strftime("%b %Y"))
                cr.set_source_rgba(*fg, 0.06)
            if d.month == 12:
                d = d.replace(year=d.year + 1, month=1)
            else:
                d = d.replace(month=d.month + 1)

        # Draw rows (skip dragged row in original position)
        for i, phase in enumerate(phases):
            if self._drag_active and i == self._drag_idx:
                continue
            y = HEADER_H + i * ROW_H
            self._draw_row(cr, w, y, i, phase, fg, dark, chart_l, chart_w, min_d, total)

        # Today marker
        today = date.today()
        if min_d <= today <= max_d:
            tx = date_to_x(today)
            # Dashed red line
            cr.set_source_rgba(0.85, 0.15, 0.15, 0.7)
            cr.set_line_width(1.5)
            cr.set_dash([6, 4])
            cr.move_to(tx, HEADER_H - 16)
            cr.line_to(tx, HEADER_H + len(phases) * ROW_H)
            cr.stroke()
            cr.set_dash([])
            # "Today" label
            cr.set_source_rgba(0.85, 0.15, 0.15, 0.9)
            cr.select_font_face("Sans", 0, 1)
            cr.set_font_size(9)
            ext = cr.text_extents("Today")
            cr.move_to(tx - ext.width / 2, HEADER_H - 20)
            cr.show_text("Today")

        # Connection arrows between sequential phases
        cr.set_source_rgba(*fg, 0.08)
        cr.set_line_width(1)
        for i in range(len(phases) - 1):
            if self._drag_active and (i == self._drag_idx or i + 1 == self._drag_idx):
                continue
            try:
                ed = date.fromisoformat(phases[i].end_date)
                sd_next = date.fromisoformat(phases[i + 1].start_date)
            except ValueError:
                continue
            x1 = date_to_x(ed)
            x2 = date_to_x(sd_next)
            y1 = HEADER_H + i * ROW_H + ROW_H / 2
            y2 = HEADER_H + (i + 1) * ROW_H + ROW_H / 2
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()
            # Arrowhead
            angle = math.atan2(y2 - y1, x2 - x1)
            arr = 6
            cr.move_to(x2, y2)
            cr.line_to(x2 - arr * math.cos(angle - 0.4), y2 - arr * math.sin(angle - 0.4))
            cr.move_to(x2, y2)
            cr.line_to(x2 - arr * math.cos(angle + 0.4), y2 - arr * math.sin(angle + 0.4))
            cr.stroke()

        # Drag feedback
        if self._drag_active and 0 <= self._drag_idx < len(phases):
            # Drop indicator line
            if 0 <= self._drop_idx <= len(phases):
                dy = HEADER_H + self._drop_idx * ROW_H
                cr.set_source_rgba(0.27, 0.53, 0.93, 0.8)
                cr.set_line_width(2.5)
                cr.move_to(8, dy)
                cr.line_to(w - 8, dy)
                cr.stroke()
                # Small circles at endpoints
                cr.arc(8, dy, 3, 0, 2 * math.pi)
                cr.fill()
                cr.arc(w - 8, dy, 3, 0, 2 * math.pi)
                cr.fill()

            # Ghost row
            ghost_y = self._drag_cur_y - ROW_H / 2
            cr.save()
            # Shadow
            cr.set_source_rgba(0, 0, 0, 0.12)
            _rounded_rect(cr, 4, ghost_y + 3, w - 8, ROW_H - 4, 8)
            cr.fill()
            # Background
            if dark:
                cr.set_source_rgba(0.18, 0.18, 0.22, 0.92)
            else:
                cr.set_source_rgba(1, 1, 1, 0.92)
            _rounded_rect(cr, 4, ghost_y, w - 8, ROW_H - 4, 8)
            cr.fill()
            phase = phases[self._drag_idx]
            self._draw_row(cr, w, ghost_y, self._drag_idx, phase, fg, dark,
                           chart_l, chart_w, min_d, total, ghost=True)
            cr.restore()

    def _draw_row(self, cr, w, y, i, phase, fg, dark, chart_l, chart_w, min_d, total, ghost=False):
        is_sel = i == self.selected_idx and not ghost
        is_hover = i == self._hover_idx and not ghost

        # Selection highlight
        if is_sel:
            cr.set_source_rgba(*fg, 0.08)
            _rounded_rect(cr, 4, y + 2, w - 8, ROW_H - 4, 6)
            cr.fill()
        elif is_hover:
            cr.set_source_rgba(*fg, 0.04)
            _rounded_rect(cr, 4, y + 2, w - 8, ROW_H - 4, 6)
            cr.fill()
        # Alternating subtle background
        elif i % 2 == 0 and not ghost:
            cr.set_source_rgba(*fg, 0.015)
            cr.rectangle(0, y, w, ROW_H)
            cr.fill()

        # Phase name
        cr.set_source_rgba(*fg, 0.85)
        cr.select_font_face("Sans", 0, 1 if is_sel else 0)
        cr.set_font_size(12)
        name = phase.name
        if len(name) > 24:
            name = name[:23] + "…"
        cr.move_to(16, y + ROW_H / 2 + 4)
        cr.show_text(name)

        # Phase bar
        try:
            sd = date.fromisoformat(phase.start_date)
            ed = date.fromisoformat(phase.end_date)
        except ValueError:
            return

        def date_to_x(d):
            return chart_l + ((d - min_d).days / total) * chart_w

        x1 = date_to_x(sd)
        x2 = date_to_x(ed)
        bw = max(x2 - x1, 8)
        by = y + 10
        bh = ROW_H - 24

        color = STATUS_COLORS[min(phase.status, 2)]
        r, g, b = _hex(color)

        # Gradient bar
        import cairo
        pat = cairo.LinearGradient(x1, by, x1, by + bh)
        pat.add_color_stop_rgba(0, min(r + 0.12, 1), min(g + 0.12, 1), min(b + 0.12, 1), 0.85)
        pat.add_color_stop_rgba(1, r, g, b, 0.75)
        cr.set_source(pat)
        _rounded_rect(cr, x1, by, bw, bh, 5)
        cr.fill()

        # Subtle top highlight
        cr.set_source_rgba(1, 1, 1, 0.15)
        cr.set_line_width(1)
        cr.move_to(x1 + 5, by + 1)
        cr.line_to(x1 + bw - 5, by + 1)
        cr.stroke()

        # Status text on bar
        cr.set_source_rgba(1, 1, 1, 0.92)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(10)
        st = STATUS_LABELS[min(phase.status, 2)]
        ext = cr.text_extents(st)
        if ext.width + 10 < bw:
            cr.move_to(x1 + bw / 2 - ext.width / 2, by + bh / 2 + ext.height / 2 - 1)
            cr.show_text(st)

        # Date range below bar
        cr.set_source_rgba(*fg, 0.3)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(8.5)
        dr = f"{phase.start_date} → {phase.end_date}"
        cr.move_to(x1, y + ROW_H - 3)
        cr.show_text(dr)

    def _draw_empty_state(self, cr, w, h, fg, dark):
        # Placeholder gantt illustration
        cx, cy = w / 2, h / 2 - 30
        bars = [(cx - 100, cy - 30, 120, 16, 0.12),
                (cx - 60, cy - 6, 150, 16, 0.08),
                (cx - 20, cy + 18, 100, 16, 0.06)]
        for bx, by, bw, bh, alpha in bars:
            cr.set_source_rgba(*fg, alpha)
            _rounded_rect(cr, bx, by, bw, bh, 4)
            cr.fill()

        cr.set_source_rgba(*fg, 0.3)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(14)
        t = "No phases yet"
        ext = cr.text_extents(t)
        cr.move_to(w / 2 - ext.width / 2, cy + 65)
        cr.show_text(t)

        cr.set_source_rgba(*fg, 0.2)
        cr.set_font_size(11)
        t2 = "Click the + button to add your first phase"
        ext2 = cr.text_extents(t2)
        cr.move_to(w / 2 - ext2.width / 2, cy + 85)
        cr.show_text(t2)

    # ── Interaction ──────────────────────────────────────────────

    def _row_at_y(self, y):
        idx = int((y - HEADER_H) / ROW_H)
        if 0 <= idx < len(self.phases):
            return idx
        return -1

    def _on_click(self, gesture, n_press, x, y):
        idx = self._row_at_y(y)
        if 0 <= idx < len(self.phases):
            self.selected_idx = idx
        else:
            self.selected_idx = -1
        self._update_buttons()
        self.canvas.queue_draw()
        if n_press == 2 and self.selected_idx >= 0:
            self._on_edit(None)

    def _on_drag_begin(self, gesture, start_x, start_y):
        idx = self._row_at_y(start_y)
        if idx >= 0 and start_x < NAME_W:
            self._drag_idx = idx
            self._drag_offset_y = start_y - (HEADER_H + idx * ROW_H + ROW_H / 2)
            self._drag_cur_y = start_y
            self._drag_active = False
            self.selected_idx = idx
            self._update_buttons()
        else:
            self._drag_idx = -1

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self._drag_idx < 0:
            return
        if not self._drag_active and abs(offset_y) < DRAG_THRESHOLD:
            return
        self._drag_active = True
        _, start_y = gesture.get_start_point()
        self._drag_cur_y = start_y + offset_y
        # Calculate drop index
        rel_y = self._drag_cur_y - HEADER_H
        drop = max(0, min(len(self.phases), round(rel_y / ROW_H)))
        self._drop_idx = drop
        self.canvas.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        if self._drag_active and self._drag_idx >= 0 and self._drop_idx >= 0:
            old_idx = self._drag_idx
            new_idx = self._drop_idx
            if new_idx > old_idx:
                new_idx -= 1
            if old_idx != new_idx and 0 <= new_idx < len(self.phases):
                phase = self.phases.pop(old_idx)
                self.phases.insert(new_idx, phase)
                order = [p.id for p in self.phases]
                self.db.reorder_phases(order)
                self.selected_idx = new_idx
        self._drag_idx = -1
        self._drag_active = False
        self._drop_idx = -1
        self._refresh()

    def _on_motion(self, controller, x, y):
        idx = self._row_at_y(y)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.canvas.queue_draw()

    def _on_leave(self, controller):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.canvas.queue_draw()

    def _on_move_up(self, _btn):
        if self.selected_idx <= 0:
            return
        i = self.selected_idx
        self.phases[i], self.phases[i - 1] = self.phases[i - 1], self.phases[i]
        order = [p.id for p in self.phases]
        self.db.reorder_phases(order)
        self.selected_idx = i - 1
        self._refresh()
        if self.on_change:
            self.on_change()

    def _on_move_down(self, _btn):
        if self.selected_idx < 0 or self.selected_idx >= len(self.phases) - 1:
            return
        i = self.selected_idx
        self.phases[i], self.phases[i + 1] = self.phases[i + 1], self.phases[i]
        order = [p.id for p in self.phases]
        self.db.reorder_phases(order)
        self.selected_idx = i + 1
        self._refresh()
        if self.on_change:
            self.on_change()

    # ── CRUD ─────────────────────────────────────────────────────

    def _on_add(self, _btn):
        from dialogs import PhaseDialog
        dlg = PhaseDialog(self.get_root())
        dlg.set_callback(self._save_new_phase)
        dlg.present()

    def _save_new_phase(self, phase):
        phase.project_id = self.project_id
        phase.position = len(self.phases)
        self.db.add_phase(phase)
        self._refresh()
        if self.on_change:
            self.on_change()

    def _on_edit(self, _btn):
        if self.selected_idx < 0:
            return
        from dialogs import PhaseDialog
        phase = self.phases[self.selected_idx]
        dlg = PhaseDialog(self.get_root(), phase=phase)
        dlg.set_callback(self._save_edited_phase)
        dlg.present()

    def _save_edited_phase(self, phase):
        self.db.update_phase(phase)
        self._refresh()
        if self.on_change:
            self.on_change()

    def _on_delete(self, _btn):
        if self.selected_idx < 0:
            return
        phase = self.phases[self.selected_idx]
        d = Adw.MessageDialog(heading="Delete Phase?",
                              body=f'Delete "{phase.name}"?',
                              transient_for=self.get_root())
        d.add_response("cancel", "Cancel")
        d.add_response("delete", "Delete")
        d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _, r: self._confirm_delete(r, phase.id))
        d.present()

    def _confirm_delete(self, resp, pid):
        if resp == "delete":
            self.db.delete_phase(pid)
            self.selected_idx = -1
            self._refresh()
            if self.on_change:
                self.on_change()
