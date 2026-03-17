#!/usr/bin/python3
"""Mind map view with pan/zoom canvas, draggable nodes, and polished visuals."""

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

from database import Database
from models import MindMapNode

NODE_COLORS = ["#4488ff", "#e04040", "#40c060", "#e88800", "#9055ff",
               "#ff55aa", "#00b4a0", "#ff6644"]

MIN_ZOOM = 0.15
MAX_ZOOM = 4.0
ZOOM_STEP = 0.1


def _hex(c):
    return int(c[1:3], 16) / 255, int(c[3:5], 16) / 255, int(c[5:7], 16) / 255


def _fg():
    dark = Adw.StyleManager.get_default().get_dark()
    return (1, 1, 1) if dark else (0, 0, 0)


def _is_dark():
    return Adw.StyleManager.get_default().get_dark()


class MindMapView(Gtk.Box):

    def __init__(self, db: Database, on_change=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.db = db
        self.on_change = on_change
        self.mindmap_id = None
        self.mindmap_name = ""
        self.nodes = []
        self.selected_id = None

        # Canvas state
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._hover_id = None
        self._drag_node = None
        self._drag_start_wx = 0.0
        self._drag_start_wy = 0.0
        self._last_mouse_x = 0.0
        self._last_mouse_y = 0.0
        self._panning = False
        self._pan_start_px = 0.0
        self._pan_start_py = 0.0

        # ── Toolbar ──────────────────────────────────────────────
        tb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                     margin_start=16, margin_end=16, margin_top=10, margin_bottom=6)
        tb.add_css_class("view-toolbar")
        self.append(tb)

        self.title_label = Gtk.Label(label="Mind Map", xalign=0, hexpand=True)
        self.title_label.add_css_class("card-title")
        tb.append(self.title_label)

        # Zoom controls
        zm_btn = Gtk.Button(icon_name="zoom-out-symbolic", tooltip_text="Zoom Out")
        zm_btn.add_css_class("flat")
        zm_btn.connect("clicked", lambda _: self._zoom_by(-ZOOM_STEP))
        tb.append(zm_btn)

        self.zoom_label = Gtk.Label(label="100%")
        self.zoom_label.add_css_class("zoom-label")
        tb.append(self.zoom_label)

        zp_btn = Gtk.Button(icon_name="zoom-in-symbolic", tooltip_text="Zoom In")
        zp_btn.add_css_class("flat")
        zp_btn.connect("clicked", lambda _: self._zoom_by(ZOOM_STEP))
        tb.append(zp_btn)

        zf_btn = Gtk.Button(icon_name="zoom-fit-best-symbolic", tooltip_text="Fit All")
        zf_btn.add_css_class("flat")
        zf_btn.connect("clicked", lambda _: self._zoom_fit())
        tb.append(zf_btn)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        tb.append(sep)

        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Child")
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

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, margin_start=4, margin_end=4)
        tb.append(sep2)

        auto_btn = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Auto Layout")
        auto_btn.add_css_class("flat")
        auto_btn.connect("clicked", self._on_auto_layout)
        tb.append(auto_btn)

        # ── Canvas ───────────────────────────────────────────────
        self.canvas = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.canvas.set_draw_func(self._draw)
        self.append(self.canvas)

        # Click gesture (select / double-click edit)
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._on_click)
        self.canvas.add_controller(click)

        # Drag gesture for nodes (button 1)
        drag1 = Gtk.GestureDrag(button=1)
        drag1.connect("drag-begin", self._on_drag_begin)
        drag1.connect("drag-update", self._on_drag_update)
        drag1.connect("drag-end", self._on_drag_end)
        self.canvas.add_controller(drag1)

        # Pan gesture (button 2 = middle, button 3 = right)
        for btn in (2, 3):
            pan_g = Gtk.GestureDrag(button=btn)
            pan_g.connect("drag-begin", self._on_pan_begin)
            pan_g.connect("drag-update", self._on_pan_update)
            self.canvas.add_controller(pan_g)

        # Scroll to zoom
        scroll_ctrl = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll_ctrl.connect("scroll", self._on_scroll)
        self.canvas.add_controller(scroll_ctrl)

        # Motion for hover tracking
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.canvas.add_controller(motion)

    # ── Public ───────────────────────────────────────────────────

    def load(self, mindmap_id: int, name: str):
        self.mindmap_id = mindmap_id
        self.mindmap_name = name
        self.title_label.set_label(f"Mind Map: {name}")
        self.selected_id = None
        self._hover_id = None
        self._refresh()
        self._zoom_fit()

    def _refresh(self):
        self.nodes = self.db.get_nodes(self.mindmap_id) if self.mindmap_id else []
        # If all positions are None, run auto-layout and persist
        if self.nodes and all(n.pos_x is None for n in self.nodes):
            self._auto_layout()
            self._save_all_positions()
        self.canvas.queue_draw()
        self._update_buttons()

    def _update_buttons(self):
        sel = self.selected_id is not None
        self.edit_btn.set_sensitive(sel)
        root = self._root()
        self.del_btn.set_sensitive(sel and (root is None or self.selected_id != root.id))

    def _root(self):
        for n in self.nodes:
            if n.parent_id is None:
                return n
        return None

    # ── Coordinate Helpers ───────────────────────────────────────

    def _screen_to_world(self, sx, sy):
        wx = (sx - self._pan_x) / self._zoom
        wy = (sy - self._pan_y) / self._zoom
        return wx, wy

    def _world_to_screen(self, wx, wy):
        sx = wx * self._zoom + self._pan_x
        sy = wy * self._zoom + self._pan_y
        return sx, sy

    def _hit_test(self, wx, wy):
        """Return the node under world coords, or None."""
        # Check in reverse so top-drawn nodes take priority
        for nd in reversed(self.nodes):
            if nd.pos_x is None:
                continue
            is_root = nd.parent_id is None
            nw = max(len(nd.text) * 9 + 36, 90 if is_root else 70)
            nh = 44 if is_root else 36
            if (nd.pos_x - nw / 2 <= wx <= nd.pos_x + nw / 2 and
                    nd.pos_y - nh / 2 <= wy <= nd.pos_y + nh / 2):
                return nd
        return None

    # ── Zoom ─────────────────────────────────────────────────────

    def _zoom_by(self, delta, cx=None, cy=None):
        old_zoom = self._zoom
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom + delta))
        if cx is not None and cy is not None:
            # Zoom toward cursor
            self._pan_x = cx - (cx - self._pan_x) * (self._zoom / old_zoom)
            self._pan_y = cy - (cy - self._pan_y) * (self._zoom / old_zoom)
        self.zoom_label.set_label(f"{int(self._zoom * 100)}%")
        self.canvas.queue_draw()

    def _zoom_fit(self):
        if not self.nodes or all(n.pos_x is None for n in self.nodes):
            self._zoom = 1.0
            alloc = self.canvas.get_allocation()
            self._pan_x = alloc.width / 2 if alloc.width > 1 else 300
            self._pan_y = alloc.height / 2 if alloc.height > 1 else 250
            self.zoom_label.set_label("100%")
            self.canvas.queue_draw()
            return
        xs = [n.pos_x for n in self.nodes if n.pos_x is not None]
        ys = [n.pos_y for n in self.nodes if n.pos_y is not None]
        if not xs:
            return
        mn_x, mx_x = min(xs) - 80, max(xs) + 80
        mn_y, mx_y = min(ys) - 50, max(ys) + 50
        alloc = self.canvas.get_allocation()
        cw = max(alloc.width, 400)
        ch = max(alloc.height, 300)
        margin = 60
        zx = (cw - margin) / max(mx_x - mn_x, 1)
        zy = (ch - margin) / max(mx_y - mn_y, 1)
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, min(zx, zy)))
        center_wx = (mn_x + mx_x) / 2
        center_wy = (mn_y + mx_y) / 2
        self._pan_x = cw / 2 - center_wx * self._zoom
        self._pan_y = ch / 2 - center_wy * self._zoom
        self.zoom_label.set_label(f"{int(self._zoom * 100)}%")
        self.canvas.queue_draw()

    # ── Layout ───────────────────────────────────────────────────

    def _auto_layout(self):
        if not self.nodes:
            return
        children = {}
        root = None
        for n in self.nodes:
            children.setdefault(n.parent_id, []).append(n)
            if n.parent_id is None:
                root = n
        if not root:
            return

        # Auto-assign colors
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
                kx = 220 * math.cos(mid)
                ky = 220 * math.sin(mid)
                layout_subtree(kid, kx, ky, cur, cur + span, 180)
                cur += span

    def _propagate_color(self, node, children):
        for kid in children.get(node.id, []):
            kid.color = node.color
            self._propagate_color(kid, children)

    def _save_all_positions(self):
        for n in self.nodes:
            if n.pos_x is not None and n.id is not None:
                self.db.update_node_position(n.id, n.pos_x, n.pos_y)

    # ── Drawing ──────────────────────────────────────────────────

    def _draw(self, area, cr, w, h):
        dark = _is_dark()
        fg = _fg()
        nodes = self.nodes

        # Background
        if dark:
            cr.set_source_rgb(0.12, 0.12, 0.14)
        else:
            cr.set_source_rgb(0.96, 0.96, 0.97)
        cr.paint()

        # Dot grid (only at reasonable zoom)
        if self._zoom > 0.3:
            grid = 40
            alpha = min(0.12, 0.04 * self._zoom)
            if dark:
                cr.set_source_rgba(1, 1, 1, alpha)
            else:
                cr.set_source_rgba(0, 0, 0, alpha)
            # Calculate visible world bounds
            w0x, w0y = self._screen_to_world(0, 0)
            w1x, w1y = self._screen_to_world(w, h)
            start_x = int(w0x / grid) * grid
            start_y = int(w0y / grid) * grid
            dot_r = max(1.0, 1.5 * self._zoom)
            gx = start_x
            while gx <= w1x:
                gy = start_y
                while gy <= w1y:
                    sx, sy = self._world_to_screen(gx, gy)
                    cr.arc(sx, sy, dot_r, 0, 2 * math.pi)
                    cr.fill()
                    gy += grid
                gx += grid

        if not nodes:
            cr.set_source_rgba(*fg, 0.35)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(14)
            t = "Empty mind map — add a child node to get started"
            ext = cr.text_extents(t)
            cr.move_to(w / 2 - ext.width / 2, h / 2)
            cr.show_text(t)
            return

        node_map = {n.id: n for n in nodes}

        # Apply canvas transform
        cr.save()
        cr.translate(self._pan_x, self._pan_y)
        cr.scale(self._zoom, self._zoom)

        # Draw connections
        for n in nodes:
            if n.parent_id and n.parent_id in node_map and n.pos_x is not None:
                p = node_map[n.parent_id]
                if p.pos_x is None:
                    continue
                r, g, b = _hex(n.color)
                # Thicker connections for shallower depth
                depth = self._node_depth(n, node_map)
                lw = max(1.0, 3.0 - depth * 0.5)
                cr.set_source_rgba(r, g, b, 0.35)
                cr.set_line_width(lw)
                # Smooth bezier
                dx = n.pos_x - p.pos_x
                dy = n.pos_y - p.pos_y
                cx1 = p.pos_x + dx * 0.4
                cy1 = p.pos_y
                cx2 = n.pos_x - dx * 0.4
                cy2 = n.pos_y
                cr.move_to(p.pos_x, p.pos_y)
                cr.curve_to(cx1, cy1, cx2, cy2, n.pos_x, n.pos_y)
                cr.stroke()

        # Draw nodes (shadows first for hovered/selected)
        for n in nodes:
            if n.pos_x is None:
                continue
            is_hover = n.id == self._hover_id
            is_sel = n.id == self.selected_id
            if is_hover or is_sel:
                is_root = n.parent_id is None
                nw, nh = self._node_size(n)
                nx = n.pos_x - nw / 2
                ny = n.pos_y - nh / 2
                rad = nh / 2
                # Shadow
                cr.set_source_rgba(0, 0, 0, 0.15)
                self._pill(cr, nx + 2, ny + 3, nw, nh, rad)
                cr.fill()

        # Draw node bodies
        for n in nodes:
            if n.pos_x is None:
                continue
            is_root = n.parent_id is None
            is_sel = n.id == self.selected_id
            is_hover = n.id == self._hover_id
            r, g, b = _hex(n.color)

            nw, nh = self._node_size(n)
            nx = n.pos_x - nw / 2
            ny = n.pos_y - nh / 2
            rad = nh / 2

            # Glow ring for selected
            if is_sel:
                cr.set_source_rgba(r, g, b, 0.25)
                self._pill(cr, nx - 4, ny - 4, nw + 8, nh + 8, rad + 4)
                cr.fill()

            # Gradient fill
            import cairo
            pat = cairo.LinearGradient(nx, ny, nx, ny + nh)
            if is_sel:
                pat.add_color_stop_rgba(0, r, g, b, 0.50)
                pat.add_color_stop_rgba(1, r, g, b, 0.35)
            elif is_hover:
                pat.add_color_stop_rgba(0, r, g, b, 0.30)
                pat.add_color_stop_rgba(1, r, g, b, 0.18)
            else:
                pat.add_color_stop_rgba(0, r, g, b, 0.18)
                pat.add_color_stop_rgba(1, r, g, b, 0.08)
            cr.set_source(pat)
            self._pill(cr, nx, ny, nw, nh, rad)
            cr.fill()

            # Border
            cr.set_source_rgba(r, g, b, 0.8 if is_sel else (0.5 if is_hover else 0.35))
            cr.set_line_width(2.5 if is_sel else (2.0 if is_hover else 1.2))
            self._pill(cr, nx, ny, nw, nh, rad)
            cr.stroke()

            # Text
            cr.select_font_face("Sans", 0, 1 if is_root else 0)
            cr.set_font_size(14 if is_root else 12)
            ext = cr.text_extents(n.text)
            cr.set_source_rgba(*fg, 0.92)
            cr.move_to(n.pos_x - ext.width / 2, n.pos_y + ext.height / 2 - 1)
            cr.show_text(n.text)

        cr.restore()

    def _node_size(self, n):
        is_root = n.parent_id is None
        nw = max(len(n.text) * 9 + 36, 90 if is_root else 70)
        nh = 44 if is_root else 36
        return nw, nh

    def _node_depth(self, n, node_map):
        depth = 0
        cur = n
        while cur.parent_id and cur.parent_id in node_map:
            depth += 1
            cur = node_map[cur.parent_id]
        return depth

    @staticmethod
    def _pill(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.move_to(x + r, y)
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    # ── Interaction ──────────────────────────────────────────────

    def _on_click(self, gesture, n_press, sx, sy):
        wx, wy = self._screen_to_world(sx, sy)
        hit = self._hit_test(wx, wy)
        self.selected_id = hit.id if hit else None
        self._update_buttons()
        self.canvas.queue_draw()
        if n_press == 2 and hit:
            self._on_edit(None)

    def _on_drag_begin(self, gesture, start_x, start_y):
        wx, wy = self._screen_to_world(start_x, start_y)
        hit = self._hit_test(wx, wy)
        if hit:
            self._drag_node = hit
            self._drag_start_wx = hit.pos_x
            self._drag_start_wy = hit.pos_y
            self.selected_id = hit.id
            self._update_buttons()
        else:
            self._drag_node = None
            self._panning = True
            self._pan_start_px = self._pan_x
            self._pan_start_py = self._pan_y

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self._drag_node:
            dx = offset_x / self._zoom
            dy = offset_y / self._zoom
            self._drag_node.pos_x = self._drag_start_wx + dx
            self._drag_node.pos_y = self._drag_start_wy + dy
            self.canvas.queue_draw()
        elif self._panning:
            self._pan_x = self._pan_start_px + offset_x
            self._pan_y = self._pan_start_py + offset_y
            self.canvas.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        if self._drag_node:
            # Persist position
            self.db.update_node_position(
                self._drag_node.id, self._drag_node.pos_x, self._drag_node.pos_y
            )
            self._drag_node = None
        self._panning = False

    def _on_pan_begin(self, gesture, start_x, start_y):
        self._pan_start_px = self._pan_x
        self._pan_start_py = self._pan_y

    def _on_pan_update(self, gesture, offset_x, offset_y):
        self._pan_x = self._pan_start_px + offset_x
        self._pan_y = self._pan_start_py + offset_y
        self.canvas.queue_draw()

    def _on_scroll(self, controller, dx, dy):
        # Get pointer position for zoom-toward-cursor
        seat = Gdk.Display.get_default().get_default_seat()
        if seat:
            alloc = self.canvas.get_allocation()
            # Use last known mouse position
            cx, cy = self._last_mouse_x, self._last_mouse_y
        else:
            alloc = self.canvas.get_allocation()
            cx, cy = alloc.width / 2, alloc.height / 2
        delta = -dy * ZOOM_STEP * 0.8
        self._zoom_by(delta, cx, cy)
        return True

    def _on_motion(self, controller, x, y):
        self._last_mouse_x = x
        self._last_mouse_y = y
        wx, wy = self._screen_to_world(x, y)
        hit = self._hit_test(wx, wy)
        new_hover = hit.id if hit else None
        if new_hover != self._hover_id:
            self._hover_id = new_hover
            self.canvas.queue_draw()

    def _on_leave(self, controller):
        if self._hover_id is not None:
            self._hover_id = None
            self.canvas.queue_draw()

    def _on_auto_layout(self, _btn):
        if self.mindmap_id:
            self.db.reset_node_positions(self.mindmap_id)
            self.nodes = self.db.get_nodes(self.mindmap_id)
            self._auto_layout()
            self._save_all_positions()
            self._zoom_fit()

    # ── CRUD ─────────────────────────────────────────────────────

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
        # Place near parent
        parent = next((n for n in self.nodes if n.id == parent_id), None)
        if parent and parent.pos_x is not None:
            angle = len([n for n in self.nodes if n.parent_id == parent_id]) * 0.8
            node.pos_x = parent.pos_x + 150 * math.cos(angle)
            node.pos_y = parent.pos_y + 150 * math.sin(angle)
        else:
            node.pos_x = 0.0
            node.pos_y = 0.0
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
