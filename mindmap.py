#!/usr/bin/python3
"""Mind map view with radial tree layout and interactive nodes."""

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

from database import Database
from models import MindMapNode

NODE_COLORS = ["#4488ff", "#e04040", "#40c060", "#e88800", "#9055ff",
               "#ff55aa", "#00b4a0", "#ff6644"]


def _hex(c):
    return int(c[1:3], 16) / 255, int(c[3:5], 16) / 255, int(c[5:7], 16) / 255


def _fg():
    dark = Adw.StyleManager.get_default().get_dark()
    return (1, 1, 1) if dark else (0, 0, 0)


class MindMapView(Gtk.Box):

    def __init__(self, db: Database, on_change=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.db = db
        self.on_change = on_change
        self.mindmap_id = None
        self.mindmap_name = ""
        self.nodes = []
        self.selected_id = None
        self._offset_x = 0
        self._offset_y = 0

        # Toolbar
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                     margin_start=20, margin_end=20, margin_top=12, margin_bottom=8)
        self.append(tb)

        self.title_label = Gtk.Label(label="Mind Map", xalign=0, hexpand=True)
        self.title_label.add_css_class("card-title")
        tb.append(self.title_label)

        add_btn = Gtk.Button(label="Add Child", tooltip_text="Add child to selected node")
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

        # Canvas
        scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self.append(scroll)
        self.canvas = Gtk.DrawingArea()
        self.canvas.set_draw_func(self._draw)
        scroll.set_child(self.canvas)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.canvas.add_controller(click)

    def load(self, mindmap_id: int, name: str):
        self.mindmap_id = mindmap_id
        self.mindmap_name = name
        self.title_label.set_label(f"Mind Map: {name}")
        self.selected_id = None
        self._refresh()

    def _refresh(self):
        self.nodes = self.db.get_nodes(self.mindmap_id) if self.mindmap_id else []
        self._layout()
        self._update_canvas_size()
        self.canvas.queue_draw()
        self._update_buttons()

    def _update_buttons(self):
        sel = self.selected_id is not None
        self.edit_btn.set_sensitive(sel)
        # Can't delete root
        root = self._root()
        self.del_btn.set_sensitive(sel and (root is None or self.selected_id != root.id))

    def _root(self):
        for n in self.nodes:
            if n.parent_id is None:
                return n
        return None

    # ── Layout ──────────────────────────────────────────────────

    def _layout(self):
        if not self.nodes:
            return
        children = {}
        node_map = {}
        root = None
        for n in self.nodes:
            node_map[n.id] = n
            children.setdefault(n.parent_id, []).append(n)
            if n.parent_id is None:
                root = n
        if not root:
            return

        # Auto-assign colors to first-level children
        first_kids = children.get(root.id, [])
        for i, kid in enumerate(first_kids):
            kid.color = NODE_COLORS[i % len(NODE_COLORS)]
            self._propagate_color(kid, children)

        def count_leaves(nid):
            kids = children.get(nid, [])
            return sum(count_leaves(k.id) for k in kids) if kids else 1

        def layout_subtree(node, cx, cy, a_start, a_end, radius):
            node.pos_x = cx
            node.pos_y = cy
            kids = children.get(node.id, [])
            if not kids:
                return
            total = sum(count_leaves(k.id) for k in kids) or 1
            cur = a_start
            for kid in kids:
                span = (count_leaves(kid.id) / total) * (a_end - a_start)
                mid = cur + span / 2
                kx = cx + radius * math.cos(mid)
                ky = cy + radius * math.sin(mid)
                layout_subtree(kid, kx, ky, cur, cur + span, radius * 0.72)
                cur += span

        root.pos_x = 0
        root.pos_y = 0
        kids = children.get(root.id, [])
        if kids:
            total = sum(count_leaves(k.id) for k in kids) or 1
            cur = 0
            step = 2 * math.pi
            for kid in kids:
                span = (count_leaves(kid.id) / total) * step
                mid = cur + span / 2
                kx = 200 * math.cos(mid)
                ky = 200 * math.sin(mid)
                layout_subtree(kid, kx, ky, cur, cur + span, 160)
                cur += span

    def _propagate_color(self, node, children):
        for kid in children.get(node.id, []):
            kid.color = node.color
            self._propagate_color(kid, children)

    def _update_canvas_size(self):
        if not self.nodes:
            self.canvas.set_content_width(600)
            self.canvas.set_content_height(500)
            self._offset_x = 300
            self._offset_y = 250
            return
        margin = 150
        xs = [n.pos_x for n in self.nodes]
        ys = [n.pos_y for n in self.nodes]
        mn_x, mx_x = min(xs), max(xs)
        mn_y, mx_y = min(ys), max(ys)
        w = int(mx_x - mn_x + margin * 2)
        h = int(mx_y - mn_y + margin * 2)
        self.canvas.set_content_width(max(w, 600))
        self.canvas.set_content_height(max(h, 500))
        self._offset_x = -mn_x + margin
        self._offset_y = -mn_y + margin

    # ── Drawing ─────────────────────────────────────────────────

    def _draw(self, area, cr, w, h):
        fg = _fg()
        nodes = self.nodes
        if not nodes:
            cr.set_source_rgba(*fg, 0.35)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            t = "Empty mind map"
            ext = cr.text_extents(t)
            cr.move_to(w / 2 - ext.width / 2, h / 2)
            cr.show_text(t)
            return

        ox, oy = self._offset_x, self._offset_y
        cr.translate(ox, oy)
        node_map = {n.id: n for n in nodes}

        # Draw connections
        for n in nodes:
            if n.parent_id and n.parent_id in node_map:
                p = node_map[n.parent_id]
                r, g, b = _hex(n.color)
                cr.set_source_rgba(r, g, b, 0.3)
                cr.set_line_width(2.5)
                # Bezier curve
                mx = (p.pos_x + n.pos_x) / 2
                cr.move_to(p.pos_x, p.pos_y)
                cr.curve_to(mx, p.pos_y, mx, n.pos_y, n.pos_x, n.pos_y)
                cr.stroke()

        # Draw nodes
        for n in nodes:
            is_root = n.parent_id is None
            is_sel = n.id == self.selected_id
            r, g, b = _hex(n.color)

            # Measure text
            cr.select_font_face("Sans", 0, 1 if is_root else 0)
            cr.set_font_size(14 if is_root else 12)
            ext = cr.text_extents(n.text)
            nw = ext.width + 32
            nh = 40 if is_root else 34
            nw = max(nw, 80 if is_root else 60)
            nx = n.pos_x - nw / 2
            ny = n.pos_y - nh / 2
            rad = nh / 2

            # Background
            if is_sel:
                cr.set_source_rgba(r, g, b, 0.35)
            else:
                cr.set_source_rgba(r, g, b, 0.12)
            self._pill(cr, nx, ny, nw, nh, rad)
            cr.fill()

            # Border
            cr.set_source_rgba(r, g, b, 0.7 if is_sel else 0.4)
            cr.set_line_width(2.5 if is_sel else 1.5)
            self._pill(cr, nx, ny, nw, nh, rad)
            cr.stroke()

            # Text
            cr.set_source_rgba(*fg, 0.9)
            cr.move_to(n.pos_x - ext.width / 2, n.pos_y + ext.height / 2 - 1)
            cr.show_text(n.text)

    @staticmethod
    def _pill(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.move_to(x + r, y)
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    # ── Interaction ─────────────────────────────────────────────

    def _on_click(self, gesture, n_press, x, y):
        ox, oy = self._offset_x, self._offset_y
        mx, my = x - ox, y - oy  # Transform to node coords
        node_map = {nd.id: nd for nd in self.nodes}

        hit = None
        for nd in self.nodes:
            is_root = nd.parent_id is None
            # Approximate node bounds
            nw = max(len(nd.text) * 8 + 32, 80 if is_root else 60)
            nh = 40 if is_root else 34
            if (nd.pos_x - nw / 2 <= mx <= nd.pos_x + nw / 2 and
                    nd.pos_y - nh / 2 <= my <= nd.pos_y + nh / 2):
                hit = nd
                break

        self.selected_id = hit.id if hit else None
        self._update_buttons()
        self.canvas.queue_draw()

    # ── CRUD ────────────────────────────────────────────────────

    def _on_add(self, _btn):
        parent_id = self.selected_id
        if parent_id is None:
            root = self._root()
            if root:
                parent_id = root.id
            else:
                return
        from dialogs import NodeDialog
        dlg = NodeDialog(self.get_root())
        dlg.set_callback(lambda nd: self._save_new_node(nd, parent_id))
        dlg.present()

    def _save_new_node(self, node, parent_id):
        node.mindmap_id = self.mindmap_id
        node.parent_id = parent_id
        self.db.add_node(node)
        self._refresh()
        if self.on_change:
            self.on_change()

    def _on_edit(self, _btn):
        if self.selected_id is None:
            return
        nd = next((n for n in self.nodes if n.id == self.selected_id), None)
        if not nd:
            return
        from dialogs import NodeDialog
        dlg = NodeDialog(self.get_root(), node=nd)
        dlg.set_callback(self._save_edited_node)
        dlg.present()

    def _save_edited_node(self, node):
        self.db.update_node(node)
        self._refresh()
        if self.on_change:
            self.on_change()

    def _on_delete(self, _btn):
        if self.selected_id is None:
            return
        root = self._root()
        if root and self.selected_id == root.id:
            return
        nd = next((n for n in self.nodes if n.id == self.selected_id), None)
        if not nd:
            return
        d = Adw.MessageDialog(heading="Delete Node?",
                              body=f'Delete "{nd.text}" and all children?',
                              transient_for=self.get_root())
        d.add_response("cancel", "Cancel")
        d.add_response("delete", "Delete")
        d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect("response", lambda _, r: self._confirm_delete(r, nd.id))
        d.present()

    def _confirm_delete(self, resp, nid):
        if resp == "delete":
            self.db.delete_node(nid)
            self.selected_id = None
            self._refresh()
            if self.on_change:
                self.on_change()
