#!/usr/bin/python3
"""Waterfall / Gantt chart view for project phases."""

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


def _hex(c):
    return int(c[1:3], 16) / 255, int(c[3:5], 16) / 255, int(c[5:7], 16) / 255


def _fg():
    dark = Adw.StyleManager.get_default().get_dark()
    return (1, 1, 1) if dark else (0, 0, 0)


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

        # Toolbar
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                     margin_start=20, margin_end=20, margin_top=12, margin_bottom=8)
        self.append(tb)

        self.title_label = Gtk.Label(label="Project", xalign=0, hexpand=True)
        self.title_label.add_css_class("card-title")
        tb.append(self.title_label)

        add_btn = Gtk.Button(label="Add Phase", tooltip_text="Add a new phase")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add)
        tb.append(add_btn)

        self.edit_btn = Gtk.Button(label="Edit", sensitive=False)
        self.edit_btn.connect("clicked", self._on_edit)
        tb.append(self.edit_btn)

        self.del_btn = Gtk.Button(label="Delete", sensitive=False)
        self.del_btn.add_css_class("destructive-action")
        self.del_btn.connect("clicked", self._on_delete)
        tb.append(self.del_btn)

        # Legend
        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16,
                         margin_start=20, margin_bottom=8)
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

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.canvas.add_controller(click)

    def load(self, project_id: int, project_name: str):
        self.project_id = project_id
        self.project_name = project_name
        self.title_label.set_label(f"Project: {project_name}")
        self.selected_idx = -1
        self._refresh()

    def _refresh(self):
        self.phases = self.db.get_phases(self.project_id) if self.project_id else []
        row_h = 48
        header = 60
        h = header + max(len(self.phases), 1) * row_h + 40
        self.canvas.set_content_height(max(h, 300))
        self.canvas.set_content_width(900)
        self.canvas.queue_draw()
        self._update_buttons()

    def _update_buttons(self):
        sel = 0 <= self.selected_idx < len(self.phases)
        self.edit_btn.set_sensitive(sel)
        self.del_btn.set_sensitive(sel)

    # ── Drawing ─────────────────────────────────────────────────

    def _draw(self, area, cr, w, h):
        fg = _fg()
        phases = self.phases
        if not phases:
            cr.set_source_rgba(*fg, 0.35)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            t = "No phases yet — click 'Add Phase' to get started"
            ext = cr.text_extents(t)
            cr.move_to(w / 2 - ext.width / 2, h / 2)
            cr.show_text(t)
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

        min_d = min(all_dates) - timedelta(days=3)
        max_d = max(all_dates) + timedelta(days=3)
        total = (max_d - min_d).days or 1

        name_w = 180
        chart_l = name_w + 20
        chart_w = w - chart_l - 20
        row_h = 48
        header_h = 50

        # Draw month grid lines
        cr.set_source_rgba(*fg, 0.06)
        d = min_d.replace(day=1)
        while d <= max_d:
            if d >= min_d:
                x = chart_l + ((d - min_d).days / total) * chart_w
                cr.move_to(x, header_h - 20)
                cr.line_to(x, header_h + len(phases) * row_h)
                cr.set_line_width(1)
                cr.stroke()
                # Month label
                cr.set_source_rgba(*fg, 0.3)
                cr.select_font_face("Sans", 0, 0)
                cr.set_font_size(10)
                cr.move_to(x + 4, header_h - 8)
                cr.show_text(d.strftime("%b %Y"))
                cr.set_source_rgba(*fg, 0.06)
            if d.month == 12:
                d = d.replace(year=d.year + 1, month=1)
            else:
                d = d.replace(month=d.month + 1)

        # Draw rows
        for i, phase in enumerate(phases):
            y = header_h + i * row_h

            # Selection highlight
            if i == self.selected_idx:
                cr.set_source_rgba(*fg, 0.06)
                cr.rectangle(0, y, w, row_h)
                cr.fill()

            # Alternating row bg
            if i % 2 == 0:
                cr.set_source_rgba(*fg, 0.02)
                cr.rectangle(0, y, w, row_h)
                cr.fill()

            # Phase name
            cr.set_source_rgba(*fg, 0.8)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(12)
            cr.move_to(16, y + row_h / 2 + 4)
            # Truncate name
            name = phase.name[:22]
            cr.show_text(name)

            # Phase bar
            try:
                sd = date.fromisoformat(phase.start_date)
                ed = date.fromisoformat(phase.end_date)
            except ValueError:
                continue
            x1 = chart_l + ((sd - min_d).days / total) * chart_w
            x2 = chart_l + ((ed - min_d).days / total) * chart_w
            bw = max(x2 - x1, 6)
            by = y + 10
            bh = row_h - 20

            color = STATUS_COLORS[min(phase.status, 2)]
            r, g, b = _hex(color)
            cr.set_source_rgba(r, g, b, 0.75)
            _rounded_rect(cr, x1, by, bw, bh, 6)
            cr.fill()

            # Status text on bar
            cr.set_source_rgba(1, 1, 1, 0.9)
            cr.set_font_size(10)
            st = STATUS_LABELS[min(phase.status, 2)]
            ext = cr.text_extents(st)
            if ext.width + 8 < bw:
                cr.move_to(x1 + bw / 2 - ext.width / 2, by + bh / 2 + ext.height / 2 - 1)
                cr.show_text(st)

            # Date range text
            cr.set_source_rgba(*fg, 0.35)
            cr.set_font_size(9)
            dr = f"{phase.start_date} → {phase.end_date}"
            cr.move_to(x1, y + row_h - 4)
            cr.show_text(dr)

    def _on_click(self, gesture, n, x, y):
        header_h = 50
        row_h = 48
        idx = int((y - header_h) / row_h)
        if 0 <= idx < len(self.phases):
            self.selected_idx = idx
        else:
            self.selected_idx = -1
        self._update_buttons()
        self.canvas.queue_draw()

    # ── CRUD ────────────────────────────────────────────────────

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
