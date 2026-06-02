"""Floating AI face widget — a JARVIS-style brain that lives on your screen.

Renders an animated sphere of brainwave particles as a frameless, always-on-top,
click-through overlay: only the glowing pixels are visible, the rest of the screen
shows through, and clicks pass to whatever is behind it.

States:
  idle       — slow, smooth orbital motion (dim cyan glow)
  listening  — fast, chaotic motion (bright green pulses)
  processing — medium speed, swirling inward (orange/amber)
  speaking   — rhythmic expansion pulses (bright cyan)

Implementation:
  * The brain is drawn with pygame to an *offscreen* surface (no pygame window).
  * Per-pixel alpha is set from luminance, so black background -> transparent and
    glow -> opaque, keeping soft edges.
  * A Qt translucent overlay window paints each frame. On GNOME/Wayland this runs
    through XWayland (QT_QPA_PLATFORM=xcb) so Mutter honours always-on-top
    (_NET_WM_STATE_ABOVE) and input passthrough.
"""

import json
import math
import os
import random
import subprocess
import threading
import time

import pygame

import config

# Force the X11 (XWayland) Qt platform BEFORE QApplication is created. On GNOME
# Wayland a native Wayland client cannot force always-on-top or click-through;
# XWayland windows can (Mutter honours _NET_WM_STATE_ABOVE + input shape).
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import QRect, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QImage, QPainter, QRegion  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
WIDTH = HEIGHT = config.OVERLAY_SIZE
FPS = 60
SCREEN_MARGIN = config.OVERLAY_MARGIN   # gap from the screen edge for the default position

NUM_PARTICLES = 120
NUM_TENDRILS = 8
TENDRIL_POINTS = 30

# State colour palettes  (r, g, b)
PALETTE = {
    "idle":       (0, 180, 220),
    "listening":  (0, 255, 120),
    "processing": (255, 160, 40),
    "speaking":   (0, 220, 255),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lerp(a, b, t):
    return a + (b - a) * t


def _lerp_color(c1, c2, t):
    return tuple(int(_lerp(c1[i], c2[i], t)) for i in range(3))


class Particle:
    """A point that orbits around the sphere surface."""

    def __init__(self, radius):
        self.base_radius = radius
        # Spherical coords
        self.theta = random.uniform(0, 2 * math.pi)
        self.phi = random.uniform(0, math.pi)
        self.speed_theta = random.uniform(0.002, 0.01) * random.choice([-1, 1])
        self.speed_phi = random.uniform(0.001, 0.005) * random.choice([-1, 1])
        self.r_offset = random.uniform(-8, 8)
        self.size = random.uniform(1.5, 3.0)
        self.noise_phase = random.uniform(0, 2 * math.pi)

    def update(self, dt, chaos, pulse):
        speed_mult = 1.0 + chaos * 4.0
        noise = math.sin(time.time() * 3 + self.noise_phase) * chaos * 12

        self.theta += self.speed_theta * speed_mult * dt * 60
        self.phi += self.speed_phi * speed_mult * dt * 60

        r = self.base_radius + self.r_offset + noise + pulse * 15
        x = r * math.sin(self.phi) * math.cos(self.theta)
        y = r * math.sin(self.phi) * math.sin(self.theta)
        z = r * math.cos(self.phi)

        # Simple depth: scale size and brightness by z
        depth = (z + self.base_radius) / (2 * self.base_radius)  # 0..1
        self.screen_x = x
        self.screen_y = y
        self.depth = max(0.15, min(1.0, depth))

    def draw(self, surface, cx, cy, color):
        sx = int(cx + self.screen_x)
        sy = int(cy + self.screen_y)
        alpha = self.depth
        c = tuple(int(v * alpha) for v in color)
        sz = max(1, int(self.size * (0.5 + 0.5 * self.depth)))
        pygame.draw.circle(surface, c, (sx, sy), sz)


class Tendril:
    """A brainwave line that wraps around the sphere."""

    def __init__(self, radius, index, total):
        self.base_radius = radius
        angle = (index / total) * 2 * math.pi
        self.base_theta = angle
        self.phase = random.uniform(0, 2 * math.pi)
        self.freq = random.uniform(2, 5)
        self.amp = random.uniform(6, 14)

    def draw(self, surface, cx, cy, color, chaos, pulse, t):
        points = []
        for i in range(TENDRIL_POINTS):
            frac = i / (TENDRIL_POINTS - 1)
            phi = frac * math.pi

            wave = math.sin(self.freq * frac * math.pi + t * 2 + self.phase)
            chaos_wave = math.sin(t * 7 + frac * 11 + self.phase) * chaos * 18
            r = self.base_radius + wave * self.amp * (1 + chaos * 2) + chaos_wave + pulse * 10

            theta = self.base_theta + math.sin(t * 0.5 + self.phase) * 0.3

            x = r * math.sin(phi) * math.cos(theta)
            y = r * math.sin(phi) * math.sin(theta)
            z = r * math.cos(phi)

            depth = (z + self.base_radius) / (2 * self.base_radius)
            depth = max(0.15, min(1.0, depth))

            sx = int(cx + x)
            sy = int(cy + y)
            points.append((sx, sy, depth))

        # Draw line segments with depth-based alpha
        for i in range(len(points) - 1):
            x1, y1, d1 = points[i]
            x2, y2, d2 = points[i + 1]
            avg_d = (d1 + d2) / 2
            c = tuple(int(v * avg_d * 0.6) for v in color)
            pygame.draw.line(surface, c, (x1, y1), (x2, y2), 1)


class CoreGlow:
    """Central glowing core."""

    def draw(self, surface, cx, cy, color, pulse):
        for r_mult in [0.7, 0.5, 0.3, 0.15]:
            radius = int(30 * (1 + pulse * 0.5) * (1.0 / (r_mult + 0.3)))
            alpha = r_mult * 0.25
            c = tuple(int(v * alpha) for v in color)
            glow_surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow_surf, (*c, int(255 * alpha * 0.4)), (radius, radius), radius)
            surface.blit(glow_surf, (cx - radius, cy - radius), special_flags=pygame.BLEND_ADD)


# ---------------------------------------------------------------------------
# Scene — holds the animated elements and draws one frame to a surface
# ---------------------------------------------------------------------------

class _Scene:
    """Owns the particles/tendrils/core and renders frames onto a surface."""

    CHAOS_MAP = {"idle": 0.0, "listening": 0.85, "processing": 0.5, "speaking": 0.35}

    def __init__(self):
        self.sphere_radius = int(WIDTH * 0.22)   # scales with the overlay size
        self.particles = [Particle(self.sphere_radius) for _ in range(NUM_PARTICLES)]
        self.tendrils = [Tendril(self.sphere_radius, i, NUM_TENDRILS) for i in range(NUM_TENDRILS)]
        self.core = CoreGlow()

        pygame.font.init()
        self.font = pygame.font.SysFont("monospace", 14, bold=True)
        self.title_font = pygame.font.SysFont("monospace", 11)

        self.state = "idle"
        self.current_color = PALETTE["idle"]
        self.target_color = PALETTE["idle"]
        self.chaos = 0.0
        self.target_chaos = 0.0
        self.pulse = 0.0
        self.status_text = "IDLE"

    def set_state(self, state):
        if state == self.state:
            return
        self.state = state
        self.target_color = PALETTE.get(state, PALETTE["idle"])
        self.target_chaos = self.CHAOS_MAP.get(state, 0.0)
        self.status_text = state.upper()

    def render(self, surface, dt, t):
        cx, cy = surface.get_width() // 2, surface.get_height() // 2

        # Smooth transitions
        lerp_speed = 3.0 * dt
        self.current_color = _lerp_color(self.current_color, self.target_color, min(1, lerp_speed))
        self.chaos = _lerp(self.chaos, self.target_chaos, min(1, lerp_speed * 1.5))

        # Breathing pulse
        if self.state == "speaking":
            self.pulse = math.sin(t * 6) * 0.5 + 0.5
        elif self.state == "listening":
            self.pulse = math.sin(t * 4) * 0.3 + math.sin(t * 7) * 0.2
        elif self.state == "processing":
            self.pulse = math.sin(t * 8) * 0.15
        else:
            self.pulse = math.sin(t * 1.5) * 0.1

        # Transparent canvas — only what we draw will show.
        surface.fill((0, 0, 0, 0))

        color = self.current_color
        self.core.draw(surface, cx, cy, color, self.pulse)

        for tendril in self.tendrils:
            tendril.draw(surface, cx, cy, color, self.chaos, self.pulse, t)

        for p in self.particles:
            p.update(dt, self.chaos, self.pulse)
            p.draw(surface, cx, cy, color)

        # Outer ring
        ring_radius = int(self.sphere_radius + 20 + self.pulse * 12)
        ring_color = tuple(int(v * 0.15) for v in color)
        pygame.draw.circle(surface, ring_color, (cx, cy), ring_radius, 1)

        # Inner ring
        inner_r = int(self.sphere_radius * 0.6 + self.pulse * 5)
        inner_c = tuple(int(v * 0.1) for v in color)
        pygame.draw.circle(surface, inner_c, (cx, cy), inner_r, 1)

        # Status text
        status_surf = self.font.render(self.status_text, True, color)
        sr = status_surf.get_rect(center=(cx, cy + self.sphere_radius + 45))
        surface.blit(status_surf, sr)

        # Title
        title_surf = self.title_font.render("J.A.R.V.I.S", True, tuple(int(v * 0.4) for v in color))
        tr = title_surf.get_rect(center=(cx, cy - self.sphere_radius - 40))
        surface.blit(title_surf, tr)


def _surface_to_qimage(surf):
    """Convert a pygame surface to a QImage, setting per-pixel alpha = luminance.

    Bright glow becomes opaque, the black background becomes fully transparent,
    and the glow keeps its soft anti-aliased falloff. Returns (QImage, buffer);
    the caller must keep `buffer` alive while the QImage is in use because QImage
    does not copy the pixel data.
    """
    rgb = pygame.surfarray.pixels3d(surf)        # [x][y][3] view
    alpha = pygame.surfarray.pixels_alpha(surf)  # [x][y] view
    alpha[:] = rgb.max(axis=2)                    # alpha follows brightness
    del rgb, alpha                                # release the surface lock

    w, h = surf.get_size()
    buf = pygame.image.tostring(surf, "RGBA")
    img = QImage(buf, w, h, QImage.Format_RGBA8888)
    return img, buf


# ---------------------------------------------------------------------------
# Qt overlay window
# ---------------------------------------------------------------------------

class _Overlay(QWidget):
    def __init__(self, scene):
        super().__init__()
        self._scene = scene
        self._surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._qimg = None
        self._buf = None
        self._last_t = time.time()
        self._drag_offset = None   # set while dragging

        flags = (
            Qt.FramelessWindowHint        # no title bar / borders
            | Qt.WindowStaysOnTopHint     # above everything (Mutter: _NET_WM_STATE_ABOVE)
            | Qt.Tool                     # no taskbar entry
        )
        if config.OVERLAY_CLICK_THROUGH:
            # Pure movie mode: every click passes through, not draggable.
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground)   # see-through window
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # don't steal focus
        self.resize(WIDTH, HEIGHT)

        if not config.OVERLAY_CLICK_THROUGH:
            # Only the brain disc receives input; the transparent corners stay
            # click-through. Lets you grab + drag the brain while clicks around
            # it still reach the apps behind.
            self.setMask(QRegion(QRect(0, 0, WIDTH, HEIGHT), QRegion.Ellipse))
            self.setCursor(Qt.OpenHandCursor)

        self._place()
        # Make the overlay follow you onto every workspace (sticky). The window
        # manager only registers the X11 window a moment after show(), so fire a
        # couple of times to beat the race.
        QTimer.singleShot(800, self._make_sticky)
        QTimer.singleShot(2500, self._make_sticky)

    def _make_sticky(self):
        """Pin the overlay to all workspaces (EWMH _NET_WM_STATE_STICKY)."""
        try:
            xid = int(self.winId())
        except (TypeError, ValueError):
            return
        cmds = (
            ["wmctrl", "-i", "-r", "0x%x" % xid, "-b", "add,sticky"],
            ["xdotool", "set_desktop_for_window", str(xid), "0xFFFFFFFF"],
        )
        for args in cmds:
            try:
                subprocess.run(args, check=False, timeout=2,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                pass

    # -- positioning / persistence -----------------------------------------

    def _place(self):
        pos = self._load_pos()
        if pos is None:
            screen = QApplication.primaryScreen().geometry()
            pos = (screen.width() - WIDTH - SCREEN_MARGIN, SCREEN_MARGIN)
        self.move(*pos)

    def _load_pos(self):
        try:
            with open(config.OVERLAY_POS_FILE) as f:
                d = json.load(f)
            return int(d["x"]), int(d["y"])
        except (OSError, ValueError, KeyError):
            return None

    def _save_pos(self):
        try:
            with open(config.OVERLAY_POS_FILE, "w") as f:
                json.dump({"x": self.x(), "y": self.y()}, f)
        except OSError:
            pass

    # -- drag to reposition (only when not click-through) ------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            self._save_pos()
            event.accept()

    def tick(self):
        now = time.time()
        dt = min(now - self._last_t, 1.0 / 15)   # clamp to avoid big jumps
        self._last_t = now
        self._scene.render(self._surface, dt, now)
        self._qimg, self._buf = _surface_to_qimage(self._surface)
        self.update()

    def paintEvent(self, event):
        if self._qimg is None:
            return
        painter = QPainter(self)
        painter.drawImage(0, 0, self._qimg)


# ---------------------------------------------------------------------------
# Public widget — same API as before (start / stop / set_state)
# ---------------------------------------------------------------------------

class FaceWidget:
    """Animated AI face overlay.

    Qt must own the main thread, so the usage pattern is:

        face = FaceWidget()
        threading.Thread(target=your_work, args=(face,), daemon=True).start()
        face.run()          # blocks on the main thread until quit()

    set_state(...) and quit() are thread-safe and may be called from the worker
    thread; they only flip flags that the Qt timer reads, never touching Qt
    objects across threads.
    """

    def __init__(self):
        self._target_state = "idle"
        self._lock = threading.Lock()
        self._running = False
        self._app = None
        self._overlay = None

    # -- thread-safe API (call from any thread) ----------------------------

    def set_state(self, state: str):
        with self._lock:
            self._target_state = state

    def quit(self):
        """Ask the Qt loop to exit. Safe to call from another thread."""
        self._running = False

    # Backwards-compatible alias.
    stop = quit

    # -- main-thread Qt loop -----------------------------------------------

    def run(self):
        """Create the overlay and run the Qt event loop. Blocks the caller."""
        self._running = True
        scene = _Scene()
        self._app = QApplication.instance() or QApplication([])
        self._overlay = _Overlay(scene)
        self._overlay.show()
        self._overlay.raise_()

        frame_timer = QTimer()
        frame_timer.timeout.connect(self._frame)
        frame_timer.start(int(1000 / FPS))

        stop_timer = QTimer()
        stop_timer.timeout.connect(self._check_stop)
        stop_timer.start(100)

        self._app.exec()

    def _frame(self):
        with self._lock:
            state = self._target_state
        self._overlay._scene.set_state(state)
        self._overlay.tick()

    def _check_stop(self):
        if not self._running and self._app is not None:
            self._app.quit()


# ---------------------------------------------------------------------------
# Standalone demo — cycle through states
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    widget = FaceWidget()

    def _demo():
        states = ["idle", "listening", "processing", "speaking"]
        idx = 0
        while True:
            time.sleep(3)
            idx = (idx + 1) % len(states)
            print(f"-> {states[idx]}")
            widget.set_state(states[idx])

    threading.Thread(target=_demo, daemon=True).start()
    try:
        widget.run()
    except KeyboardInterrupt:
        widget.quit()
