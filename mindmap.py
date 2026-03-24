#!/usr/bin/python3
"""Mind map view with pan/zoom canvas, draggable nodes, collapsible branches,
right-click context menus, and smooth animations."""

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, Gio, GLib

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


def _ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3


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

        # Context menu state
        self._context_popover = None
        self._context_node = None

        # Animation state
        self._anim_active = False
        self._anim_tick_id = None
        self._anim_start_time = None
        self._anim_duration = 0.0
        self._anim_targets = {}
        self._anim_origins = {}
        self._zoom_target = None
        self._zoom_origin = None
        self._entry_anim_nodes = {}

        # Hover transition state
        self._hover_alpha = {}
        self._hover_tick_id = None

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

        # Pan gesture (button 2 = middle)
        pan_g = Gtk.GestureDrag(button=2)
        pan_g.connect("drag-begin", self._on_pan_begin)
        pan_g.connect("drag-update", self._on_pan_update)
        self.canvas.add_controller(pan_g)

        # Right-click context menu (button 3)
        rclick = Gtk.GestureClick(button=3)
        rclick.connect("pressed", self._on_right_click)
        self.canvas.add_controller(rclick)

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
        self._hover_alpha.clear()
        self._refresh()
        self._zoom_fit(animate=False)

    def _refresh(self):
        self.nodes = self.db.get_nodes(self.mindmap_id) if self.mindmap_id else []
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

    # ── Collapse Helpers ─────────────────────────────────────────

    def _build_children_map(self):
        children = {}
        for n in self.nodes:
            children.setdefault(n.parent_id, []).append(n)
        return children

    def _hidden_ids(self):
        children_map = self._build_children_map()
        hidden = set()

        def _mark_hidden(nid):
            for child in children_map.get(nid, []):
                hidden.add(child.id)
                _mark_hidden(child.id)

        for n in self.nodes:
            if n.collapsed:
                _mark_hidden(n.id)
        return hidden

    def _has_children(self, node_id):
        return any(n.parent_id == node_id for n in self.nodes)

    def _descendant_count(self, node_id):
        children_map = self._build_children_map()
        count = 0

        def _count(nid):
            nonlocal count
            for child in children_map.get(nid, []):
                count += 1
                _count(child.id)

        _count(node_id)
        return count

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
        hidden = self._hidden_ids()
        for nd in reversed(self.nodes):
            if nd.pos_x is None or nd.id in hidden:
                continue
            is_root = nd.parent_id is None
            nw, nh = self._node_size(nd)
            if (nd.pos_x - nw / 2 <= wx <= nd.pos_x + nw / 2 and
                    nd.pos_y - nh / 2 <= wy <= nd.pos_y + nh / 2):
                return nd
        return None

    def _collapse_toggle_hit(self, wx, wy):
        """Return the node whose collapse toggle was clicked, or None."""
        hidden = self._hidden_ids()
        for nd in reversed(self.nodes):
            if nd.pos_x is None or nd.id in hidden:
                continue
            if not self._has_children(nd.id):
                continue
            nw, nh = self._node_size(nd)
            # Toggle zone: rightmost 22px of the node pill
            toggle_left = nd.pos_x + nw / 2 - 22
            if (toggle_left <= wx <= nd.pos_x + nw / 2 and
                    nd.pos_y - nh / 2 <= wy <= nd.pos_y + nh / 2):
                return nd
        return None

    # ── Zoom ─────────────────────────────────────────────────────

    def _zoom_by(self, delta, cx=None, cy=None):
        old_zoom = self._zoom
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom + delta))
        if cx is not None and cy is not None:
            self._pan_x = cx - (cx - self._pan_x) * (self._zoom / old_zoom)
            self._pan_y = cy - (cy - self._pan_y) * (self._zoom / old_zoom)
        self.zoom_label.set_label(f"{int(self._zoom * 100)}%")
        self.canvas.queue_draw()

    def _zoom_fit(self, animate=True):
        hidden = self._hidden_ids()
        visible = [n for n in self.nodes if n.pos_x is not None and n.id not in hidden]
        if not visible:
            self._zoom = 1.0
            alloc = self.canvas.get_allocation()
            self._pan_x = alloc.width / 2 if alloc.width > 1 else 300
            self._pan_y = alloc.height / 2 if alloc.height > 1 else 250
            self.zoom_label.set_label("100%")
            self.canvas.queue_draw()
            return
        xs = [n.pos_x for n in visible]
        ys = [n.pos_y for n in visible]
        mn_x, mx_x = min(xs) - 80, max(xs) + 80
        mn_y, mx_y = min(ys) - 50, max(ys) + 50
        alloc = self.canvas.get_allocation()
        cw = max(alloc.width, 400)
        ch = max(alloc.height, 300)
        margin = 60
        zx = (cw - margin) / max(mx_x - mn_x, 1)
        zy = (ch - margin) / max(mx_y - mn_y, 1)
        target_zoom = max(MIN_ZOOM, min(MAX_ZOOM, min(zx, zy)))
        center_wx = (mn_x + mx_x) / 2
        center_wy = (mn_y + mx_y) / 2
        target_pan_x = cw / 2 - center_wx * target_zoom
        target_pan_y = ch / 2 - center_wy * target_zoom

        if animate and alloc.width > 1:
            self._zoom_origin = (self._zoom, self._pan_x, self._pan_y)
            self._zoom_target = (target_zoom, target_pan_x, target_pan_y)
            self._start_animation(duration=0.4)
        else:
            self._zoom = target_zoom
            self._pan_x = target_pan_x
            self._pan_y = target_pan_y
            self.zoom_label.set_label(f"{int(self._zoom * 100)}%")
            self.canvas.queue_draw()

    # ── Animation ────────────────────────────────────────────────

    def _start_animation(self, duration=0.35):
        if self._anim_tick_id is not None:
            GLib.source_remove(self._anim_tick_id)
        self._anim_active = True
        self._anim_start_time = GLib.get_monotonic_time() / 1_000_000.0
        self._anim_duration = duration
        self._anim_tick_id = GLib.timeout_add(16, self._anim_tick)

    def _anim_tick(self):
        now = GLib.get_monotonic_time() / 1_000_000.0
        elapsed = now - self._anim_start_time
        t = min(1.0, elapsed / self._anim_duration) if self._anim_duration > 0 else 1.0
        eased = _ease_out_cubic(t)

        # Interpolate node positions
        if self._anim_targets:
            node_map = {n.id: n for n in self.nodes}
            for nid, (tx, ty) in self._anim_targets.items():
                ox, oy = self._anim_origins.get(nid, (tx, ty))
                node = node_map.get(nid)
                if node:
                    node.pos_x = ox + (tx - ox) * eased
                    node.pos_y = oy + (ty - oy) * eased

        # Interpolate zoom/pan
        if self._zoom_target:
            tz, tpx, tpy = self._zoom_target
            oz, opx, opy = self._zoom_origin
            self._zoom = oz + (tz - oz) * eased
            self._pan_x = opx + (tpx - opx) * eased
            self._pan_y = opy + (tpy - opy) * eased
            self.zoom_label.set_label(f"{int(self._zoom * 100)}%")

        # Interpolate entry animations
        for nid in list(self._entry_anim_nodes):
            self._entry_anim_nodes[nid] = min(1.0, self._entry_anim_nodes[nid] + 0.08)

        self.canvas.queue_draw()

        if t >= 1.0:
            self._finish_animation()
            return False
        return True

    def _finish_animation(self):
        if self._anim_targets:
            node_map = {n.id: n for n in self.nodes}
            for nid, (tx, ty) in self._anim_targets.items():
                node = node_map.get(nid)
                if node:
                    node.pos_x = tx
                    node.pos_y = ty
            self._save_all_positions()
        if self._zoom_target:
            tz, tpx, tpy = self._zoom_target
            self._zoom = tz
            self._pan_x = tpx
            self._pan_y = tpy
            self.zoom_label.set_label(f"{int(self._zoom * 100)}%")

        self._anim_active = False
        self._anim_tick_id = None
        self._anim_targets = {}
        self._anim_origins = {}
        self._zoom_target = None
        self._zoom_origin = None
        self._entry_anim_nodes = {}
        self.canvas.queue_draw()

    # ── Hover Transitions ────────────────────────────────────────

    def _start_hover_tick(self):
        if self._hover_tick_id:
            return
        self._hover_tick_id = GLib.timeout_add(16, self._hover_tick)

    def _hover_tick(self):
        changed = False
        target_hover = self._hover_id
        for n in self.nodes:
            target = 1.0 if n.id == target_hover else 0.0
            current = self._hover_alpha.get(n.id, 0.0)
            if abs(current - target) > 0.01:
                step = 0.12
                new_val = current + step if target > current else current - step
                new_val = max(0.0, min(1.0, new_val))
                self._hover_alpha[n.id] = new_val
                changed = True
        if changed:
            self.canvas.queue_draw()
            return True
        self._hover_tick_id = None
        return False

    # ── Layout ───────────────────────────────────────────────────

    def _auto_layout(self):
        if not self.nodes:
            return
        children = {}
        node_map = {}
        root = None
        for n in self.nodes:
            children.setdefault(n.parent_id, []).append(n)
            node_map[n.id] = n
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
            nd = node_map.get(nid)
            if nd and nd.collapsed:
                return 1
            kids = children.get(nid, [])
            return sum(count_leaves(k.id) for k in kids) if kids else 1

        def layout_subtree(node, cx, cy, a_start, a_end, radius):
            node.pos_x = cx
            node.pos_y = cy
            if node.collapsed:
                return
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
            t = "Empty mind map \u2014 add a child node to get started"
            ext = cr.text_extents(t)
            cr.move_to(w / 2 - ext.width / 2, h / 2)
            cr.show_text(t)
            return

        hidden = self._hidden_ids()
        node_map = {n.id: n for n in nodes}

        # Apply canvas transform
        cr.save()
        cr.translate(self._pan_x, self._pan_y)
        cr.scale(self._zoom, self._zoom)

        # Draw connections (tapered)
        for n in nodes:
            if n.id in hidden:
                continue
            if n.parent_id and n.parent_id in node_map and n.pos_x is not None:
                p = node_map[n.parent_id]
                if p.pos_x is None or p.id in hidden:
                    continue
                depth = self._node_depth(n, node_map)
                self._draw_tapered_connection(cr, p, n, depth)

        # Draw shadows for hovered/selected
        for n in nodes:
            if n.pos_x is None or n.id in hidden:
                continue
            hover_t = self._hover_alpha.get(n.id, 0.0)
            is_sel = n.id == self.selected_id
            if hover_t > 0.01 or is_sel:
                nw, nh = self._node_size(n)
                nx = n.pos_x - nw / 2
                ny = n.pos_y - nh / 2
                rad = nh / 2
                strength = max(hover_t, 1.0 if is_sel else 0.0)
                # Multi-layer soft shadow
                for layer in range(3):
                    offset = 2 + layer * 1.5
                    a = (0.07 - layer * 0.018) * strength
                    cr.set_source_rgba(0, 0, 0, a)
                    self._pill(cr, nx + offset * 0.5, ny + offset, nw + layer, nh + layer, rad)
                    cr.fill()

        # Draw node bodies
        import cairo
        for n in nodes:
            if n.pos_x is None or n.id in hidden:
                continue
            is_root = n.parent_id is None
            is_sel = n.id == self.selected_id
            hover_t = self._hover_alpha.get(n.id, 0.0)
            r, g, b = _hex(n.color)

            nw, nh = self._node_size(n)
            nx = n.pos_x - nw / 2
            ny = n.pos_y - nh / 2
            rad = nh / 2

            # Entry animation
            entry_p = self._entry_anim_nodes.get(n.id, 1.0)
            entry_alpha = _ease_out_cubic(entry_p)
            entry_scale = 0.5 + 0.5 * _ease_out_cubic(entry_p)
            if entry_p < 1.0:
                cr.save()
                cr.translate(n.pos_x, n.pos_y)
                cr.scale(entry_scale, entry_scale)
                cr.translate(-n.pos_x, -n.pos_y)

            # Glow ring for selected
            if is_sel:
                cr.set_source_rgba(r, g, b, 0.25 * entry_alpha)
                self._pill(cr, nx - 4, ny - 4, nw + 8, nh + 8, rad + 4)
                cr.fill()

            # Three-stop gradient fill (interpolated by hover_t)
            pat = cairo.LinearGradient(nx, ny, nx, ny + nh)
            if is_sel:
                pat.add_color_stop_rgba(0.0, r, g, b, 0.55 * entry_alpha)
                pat.add_color_stop_rgba(0.5, r, g, b, 0.42 * entry_alpha)
                pat.add_color_stop_rgba(1.0, r, g, b, 0.32 * entry_alpha)
            else:
                # Interpolate between normal and hover
                a_top = 0.18 + 0.17 * hover_t
                a_mid = 0.11 + 0.14 * hover_t
                a_bot = 0.08 + 0.10 * hover_t
                pat.add_color_stop_rgba(0.0, r, g, b, a_top * entry_alpha)
                pat.add_color_stop_rgba(0.5, r, g, b, a_mid * entry_alpha)
                pat.add_color_stop_rgba(1.0, r, g, b, a_bot * entry_alpha)
            cr.set_source(pat)
            self._pill(cr, nx, ny, nw, nh, rad)
            cr.fill()

            # Border (interpolated)
            border_a = 0.35 + 0.15 * hover_t
            border_w = 1.2 + 0.8 * hover_t
            if is_sel:
                border_a = 0.8
                border_w = 2.5
            cr.set_source_rgba(r, g, b, border_a * entry_alpha)
            cr.set_line_width(border_w)
            self._pill(cr, nx, ny, nw, nh, rad)
            cr.stroke()

            # Text
            cr.select_font_face("Sans", 0, 1 if is_root else 0)
            cr.set_font_size(14 if is_root else 12)
            ext = cr.text_extents(n.text)
            # Offset text left if node has collapse indicator
            text_offset = -9 if self._has_children(n.id) else 0
            cr.set_source_rgba(*fg, 0.92 * entry_alpha)
            cr.move_to(n.pos_x - ext.width / 2 + text_offset, n.pos_y + ext.height / 2 - 1)
            cr.show_text(n.text)

            # Collapse indicator
            if self._has_children(n.id):
                self._draw_collapse_indicator(cr, n, nw, nh, fg, entry_alpha)

            if entry_p < 1.0:
                cr.restore()

        cr.restore()

    def _draw_tapered_connection(self, cr, parent, child, depth):
        r, g, b = _hex(child.color)
        start_width = max(1.5, 4.0 - depth * 0.7)
        end_width = max(0.5, start_width * 0.35)

        px, py = parent.pos_x, parent.pos_y
        cx, cy = child.pos_x, child.pos_y
        dx = cx - px
        dy = cy - py
        cx1, cy1 = px + dx * 0.4, py
        cx2, cy2 = cx - dx * 0.4, cy

        steps = 16
        points_top = []
        points_bot = []
        for i in range(steps + 1):
            t = i / steps
            mt = 1 - t
            bx = mt**3 * px + 3 * mt**2 * t * cx1 + 3 * mt * t**2 * cx2 + t**3 * cx
            by = mt**3 * py + 3 * mt**2 * t * cy1 + 3 * mt * t**2 * cy2 + t**3 * cy

            # Tangent for perpendicular
            tbx = 3 * mt**2 * (cx1 - px) + 6 * mt * t * (cx2 - cx1) + 3 * t**2 * (cx - cx2)
            tby = 3 * mt**2 * (cy1 - py) + 6 * mt * t * (cy2 - cy1) + 3 * t**2 * (cy - cy2)
            length = math.sqrt(tbx**2 + tby**2) or 1.0
            nx_dir = -tby / length
            ny_dir = tbx / length

            width = start_width + (end_width - start_width) * t
            half_w = width / 2
            points_top.append((bx + nx_dir * half_w, by + ny_dir * half_w))
            points_bot.append((bx - nx_dir * half_w, by - ny_dir * half_w))

        cr.set_source_rgba(r, g, b, 0.30)
        cr.move_to(*points_top[0])
        for pt in points_top[1:]:
            cr.line_to(*pt)
        for pt in reversed(points_bot):
            cr.line_to(*pt)
        cr.close_path()
        cr.fill()

    def _draw_collapse_indicator(self, cr, node, nw, nh, fg, entry_alpha):
        tri_cx = node.pos_x + nw / 2 - 12
        tri_cy = node.pos_y
        tri_size = 5

        cr.set_source_rgba(*fg, 0.5 * entry_alpha)
        if node.collapsed:
            # Right-pointing triangle
            cr.move_to(tri_cx - tri_size * 0.6, tri_cy - tri_size)
            cr.line_to(tri_cx + tri_size * 0.6, tri_cy)
            cr.line_to(tri_cx - tri_size * 0.6, tri_cy + tri_size)
        else:
            # Down-pointing triangle
            cr.move_to(tri_cx - tri_size, tri_cy - tri_size * 0.6)
            cr.line_to(tri_cx, tri_cy + tri_size * 0.6)
            cr.line_to(tri_cx + tri_size, tri_cy - tri_size * 0.6)
        cr.close_path()
        cr.fill()

        # Count badge when collapsed
        if node.collapsed:
            count = self._descendant_count(node.id)
            if count > 0:
                badge_text = f"+{count}"
                cr.select_font_face("Sans", 0, 0)
                cr.set_font_size(9)
                ext = cr.text_extents(badge_text)
                badge_x = node.pos_x + nw / 2 + 6
                badge_y = node.pos_y
                badge_w = ext.width + 8
                badge_h = 16
                r, g, b = _hex(node.color)
                cr.set_source_rgba(r, g, b, 0.3 * entry_alpha)
                self._pill(cr, badge_x - badge_w / 2, badge_y - badge_h / 2,
                           badge_w, badge_h, badge_h / 2)
                cr.fill()
                cr.set_source_rgba(*fg, 0.7 * entry_alpha)
                cr.move_to(badge_x - ext.width / 2, badge_y + ext.height / 2 - 1)
                cr.show_text(badge_text)

    def _node_size(self, n):
        is_root = n.parent_id is None
        nw = max(len(n.text) * 9 + 36, 90 if is_root else 70)
        nh = 44 if is_root else 36
        if self._has_children(n.id):
            nw += 18
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
        # Check collapse toggle first
        if n_press == 1:
            toggle_node = self._collapse_toggle_hit(wx, wy)
            if toggle_node:
                toggle_node.collapsed = not toggle_node.collapsed
                self.db.update_node_collapsed(toggle_node.id, toggle_node.collapsed)
                self.canvas.queue_draw()
                return
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
        cx, cy = self._last_mouse_x, self._last_mouse_y
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
            if not self._anim_active:
                self._start_hover_tick()
            self.canvas.queue_draw()

    def _on_leave(self, controller):
        if self._hover_id is not None:
            self._hover_id = None
            if not self._anim_active:
                self._start_hover_tick()
            self.canvas.queue_draw()

    def _on_auto_layout(self, _btn):
        if not self.mindmap_id:
            return
        # Capture current positions
        origins = {}
        for n in self.nodes:
            if n.pos_x is not None:
                origins[n.id] = (n.pos_x, n.pos_y)

        self.db.reset_node_positions(self.mindmap_id)
        self.nodes = self.db.get_nodes(self.mindmap_id)
        self._auto_layout()

        # Capture target positions
        targets = {}
        for n in self.nodes:
            if n.pos_x is not None:
                targets[n.id] = (n.pos_x, n.pos_y)

        # Restore origins for animation start
        for n in self.nodes:
            if n.id in origins:
                n.pos_x, n.pos_y = origins[n.id]

        self._anim_origins = origins
        self._anim_targets = targets
        self._start_animation(duration=0.5)

    # ── Right-Click Context Menu ─────────────────────────────────

    def _on_right_click(self, gesture, n_press, sx, sy):
        wx, wy = self._screen_to_world(sx, sy)
        hit = self._hit_test(wx, wy)

        if self._context_popover:
            self._context_popover.unparent()
            self._context_popover = None

        if hit:
            self._show_node_context_menu(hit, sx, sy)
        else:
            self._show_canvas_context_menu(sx, sy)

    def _show_node_context_menu(self, node, sx, sy):
        self._context_node = node
        self.selected_id = node.id
        self._update_buttons()
        self.canvas.queue_draw()

        menu = Gio.Menu()
        menu.append("Add Child", "mm.add-child")
        menu.append("Edit", "mm.edit-node")

        if self._has_children(node.id):
            label = "Expand" if node.collapsed else "Collapse"
            menu.append(label, "mm.toggle-collapse")

        root = self._root()
        if not (root and node.id == root.id):
            menu.append("Delete", "mm.delete-node")

        # Color submenu
        color_menu = Gio.Menu()
        for i, color in enumerate(NODE_COLORS):
            color_menu.append(color, f"mm.set-color-{i}")
        menu.append_submenu("Change Color", color_menu)

        ag = Gio.SimpleActionGroup()

        a = Gio.SimpleAction(name="add-child")
        a.connect("activate", lambda *_: self._ctx_add_child())
        ag.add_action(a)

        a = Gio.SimpleAction(name="edit-node")
        a.connect("activate", lambda *_: self._on_edit(None))
        ag.add_action(a)

        a = Gio.SimpleAction(name="toggle-collapse")
        a.connect("activate", lambda *_: self._ctx_toggle_collapse())
        ag.add_action(a)

        a = Gio.SimpleAction(name="delete-node")
        a.connect("activate", lambda *_: self._on_delete(None))
        ag.add_action(a)

        for i, color in enumerate(NODE_COLORS):
            a = Gio.SimpleAction(name=f"set-color-{i}")
            a.connect("activate", lambda *_, c=color: self._ctx_set_color(c))
            ag.add_action(a)

        self.canvas.insert_action_group("mm", ag)

        rect = Gdk.Rectangle()
        rect.x = int(sx)
        rect.y = int(sy)
        rect.width = 1
        rect.height = 1

        p = Gtk.PopoverMenu(menu_model=menu, has_arrow=True, halign=Gtk.Align.START)
        p.set_parent(self.canvas)
        p.set_pointing_to(rect)
        self._context_popover = p
        p.popup()

    def _show_canvas_context_menu(self, sx, sy):
        menu = Gio.Menu()
        menu.append("Add Root Child", "mm.add-root-child")
        menu.append("Fit All", "mm.fit-all")
        menu.append("Auto Layout", "mm.auto-layout")

        ag = Gio.SimpleActionGroup()

        a = Gio.SimpleAction(name="add-root-child")
        a.connect("activate", lambda *_: self._ctx_add_root_child())
        ag.add_action(a)

        a = Gio.SimpleAction(name="fit-all")
        a.connect("activate", lambda *_: self._zoom_fit())
        ag.add_action(a)

        a = Gio.SimpleAction(name="auto-layout")
        a.connect("activate", lambda *_: self._on_auto_layout(None))
        ag.add_action(a)

        self.canvas.insert_action_group("mm", ag)

        rect = Gdk.Rectangle()
        rect.x = int(sx)
        rect.y = int(sy)
        rect.width = 1
        rect.height = 1

        p = Gtk.PopoverMenu(menu_model=menu, has_arrow=True, halign=Gtk.Align.START)
        p.set_parent(self.canvas)
        p.set_pointing_to(rect)
        self._context_popover = p
        p.popup()

    def _ctx_add_child(self):
        if self._context_node:
            self.selected_id = self._context_node.id
            self._on_add(None)

    def _ctx_add_root_child(self):
        root = self._root()
        if root:
            self.selected_id = root.id
            self._on_add(None)

    def _ctx_toggle_collapse(self):
        if self._context_node:
            self._context_node.collapsed = not self._context_node.collapsed
            self.db.update_node_collapsed(self._context_node.id, self._context_node.collapsed)
            self.canvas.queue_draw()

    def _ctx_set_color(self, color):
        if self._context_node:
            self._context_node.color = color
            self.db.update_node(self._context_node)
            children_map = self._build_children_map()
            self._propagate_color(self._context_node, children_map)
            for n in self.nodes:
                self.db.update_node(n)
            self.canvas.queue_draw()

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
        parent = next((n for n in self.nodes if n.id == parent_id), None)
        if parent and parent.pos_x is not None:
            angle = len([n for n in self.nodes if n.parent_id == parent_id]) * 0.8
            node.pos_x = parent.pos_x + 150 * math.cos(angle)
            node.pos_y = parent.pos_y + 150 * math.sin(angle)
        else:
            node.pos_x = 0.0
            node.pos_y = 0.0
        new_id = self.db.add_node(node)
        self._entry_anim_nodes[new_id] = 0.0
        self._refresh()
        self._start_animation(duration=0.3)
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
