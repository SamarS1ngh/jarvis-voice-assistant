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

import numpy as np
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

NUM_PARTICLES = 70          # fine "dust" motes
NUM_NEURONS = 44            # nodes of the synaptic mesh
CONNECT_DIST_FRAC = 0.34    # neurons closer than this (× sphere span) wire up
MEMBRANE_POINTS = 96        # resolution of the organic membrane ring
NUM_TENDRILS = 8            # retained for the standalone Tendril class
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
    """Bright central nucleus — a pixel-smooth radial gradient (numpy), so there
    is no concentric banding or hard edge."""

    def __init__(self):
        self._cache = {}   # radius -> (rgba float falloff)

    def _falloff(self, R):
        f = self._cache.get(R)
        if f is None:
            yy, xx = np.ogrid[-R:R, -R:R]
            d = np.sqrt(xx * xx + yy * yy) / R
            # circular 0..1 (1 at centre), HARD zero past the radius -> round, not square
            f = (np.clip(1.0 - d, 0.0, 1.0) ** 1.7).T   # .T: ogrid [y][x] -> surfarray [x][y]
            self._cache[R] = f
        return f

    def draw(self, surface, cx, cy, color, pulse, t):
        # Own steady breath so the nucleus visibly pulsates even when idle.
        breath = 0.5 + 0.5 * math.sin(t * 2.2)
        R = int((28 + pulse * 6) * (1 + breath * 0.30))   # bigger base + size pulse
        bright = 0.75 + 0.45 * breath                      # brightness pulse
        falloff = self._falloff(R)
        # BLEND_ADD adds RGB (ignores alpha), so bake the radial gradient into the
        # colour channels; outside the radius falloff is 0 -> adds nothing.
        g = np.stack([np.clip(color[ch] * falloff * bright, 0, 255) for ch in range(3)],
                     axis=-1).astype(np.uint8)
        glow = pygame.surfarray.make_surface(g)   # unlocked surface, safe to blit
        surface.blit(glow, (cx - R, cy - R), special_flags=pygame.BLEND_ADD)


class NeuralMesh:
    """A living web of neurons orbiting the sphere, wiring up when they drift
    close together — the synaptic body of the organism."""

    def __init__(self, radius):
        self.radius = radius
        self.connect_dist = radius * 2 * CONNECT_DIST_FRAC
        self.nodes = [Particle(radius) for _ in range(NUM_NEURONS)]
        # Each neuron carries its own firing flicker so the mesh shimmers.
        for n in self.nodes:
            n.size = random.uniform(2.0, 3.6)
            n.fire_phase = random.uniform(0, 2 * math.pi)
        self.edges = []   # (i, j) pairs that are currently wired — refreshed per frame

    def update(self, dt, chaos, pulse):
        for n in self.nodes:
            n.update(dt, chaos, pulse)
        # Rebuild the active connection list from current screen positions.
        self.edges = []
        d2max = self.connect_dist * self.connect_dist
        nodes = self.nodes
        for i in range(len(nodes)):
            xi, yi = nodes[i].screen_x, nodes[i].screen_y
            for j in range(i + 1, len(nodes)):
                dx = xi - nodes[j].screen_x
                dy = yi - nodes[j].screen_y
                d2 = dx * dx + dy * dy
                if d2 < d2max:
                    self.edges.append((i, j, d2))

    def draw(self, surface, cx, cy, color, t):
        # Synapses first, so node cells sit on top.
        for i, j, d2 in self.edges:
            a = self.nodes[i]
            b = self.nodes[j]
            closeness = 1.0 - (d2 ** 0.5) / self.connect_dist
            depth = (a.depth + b.depth) * 0.5
            strength = closeness * depth * 0.5
            c = tuple(int(v * strength) for v in color)
            pygame.draw.line(
                surface, c,
                (int(cx + a.screen_x), int(cy + a.screen_y)),
                (int(cx + b.screen_x), int(cy + b.screen_y)), 1,
            )
        # Neuron cell bodies, flickering as they "fire".
        for n in self.nodes:
            fire = 0.6 + 0.4 * math.sin(t * 5 + n.fire_phase)
            bright = n.depth * fire
            c = tuple(int(v * bright) for v in color)
            sz = max(1, int(n.size * (0.5 + 0.5 * n.depth)))
            pygame.draw.circle(surface, c, (int(cx + n.screen_x), int(cy + n.screen_y)), sz)


class Impulse:
    """A nerve impulse that races along a synapse, then jumps to a new one."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.speed = random.uniform(1.4, 2.6)
        self._respawn()

    def _respawn(self):
        edges = self.mesh.edges
        if edges:
            i, j, _ = random.choice(edges)
            self.i, self.j = (i, j) if random.random() < 0.5 else (j, i)
        else:
            self.i = self.j = random.randrange(len(self.mesh.nodes))
        self.p = 0.0

    def update(self, dt):
        self.p += self.speed * dt
        if self.p >= 1.0:
            self._respawn()

    def draw(self, surface, cx, cy, color):
        a = self.mesh.nodes[self.i]
        b = self.mesh.nodes[self.j]
        x = cx + _lerp(a.screen_x, b.screen_x, self.p)
        y = cy + _lerp(a.screen_y, b.screen_y, self.p)
        # small bright head only — no glowing halo
        head = tuple(min(255, int(v + 50)) for v in color)
        pygame.draw.circle(surface, head, (int(x), int(y)), 1)


class Membrane:
    """An organic, wobbling cell membrane — concentric living rings whose radius
    breathes with a sum of sine waves instead of being a clean circle."""

    def __init__(self, radius, layers=2):
        self.radius = radius
        self.layers = []
        for k in range(layers):
            self.layers.append({
                "scale": 1.0 - k * 0.14,
                "freqs": [random.randint(3, 7) for _ in range(3)],
                "phases": [random.uniform(0, 2 * math.pi) for _ in range(3)],
                "spin": random.uniform(-0.4, 0.4),
                "amp": random.uniform(0.06, 0.12),
            })

    def draw(self, surface, cx, cy, color, chaos, pulse, t):
        for k, lay in enumerate(self.layers):
            base = self.radius * lay["scale"] * (1 + pulse * 0.18)
            pts = []
            for s in range(MEMBRANE_POINTS + 1):
                ang = (s / MEMBRANE_POINTS) * 2 * math.pi + t * lay["spin"]
                wob = 0.0
                for f, ph in zip(lay["freqs"], lay["phases"]):
                    wob += math.sin(ang * f + t * 1.6 + ph)
                wob *= lay["amp"] * (1 + chaos * 1.8) / len(lay["freqs"])
                r = base * (1 + wob)
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
            bright = 0.35 - k * 0.1
            c = tuple(int(v * bright) for v in color)
            pygame.draw.lines(surface, c, False, pts, 1)


class RadarSweep:
    """A techno HUD shell: a rotating radar sweep with a fading wake, ringed by
    a slowly counter-rotating band of circuit segments and tick marks."""

    SWEEP_TRAIL = 14          # wedge segments trailing the sweep line
    SEGMENTS = 32             # dashes in the outer circuit ring

    def __init__(self, radius):
        self.radius = radius

    def draw(self, surface, cx, cy, color, chaos, t):
        spd = 1.1 + chaos * 2.2
        head = t * spd

        # Sweep wake — a wedge of lines fading behind the leading edge.
        for k in range(self.SWEEP_TRAIL):
            ang = head - k * 0.07
            fade = (1.0 - k / self.SWEEP_TRAIL) * 0.5
            c = tuple(int(v * fade) for v in color)
            ex = cx + self.radius * math.cos(ang)
            ey = cy + self.radius * math.sin(ang)
            pygame.draw.line(surface, c, (cx, cy), (int(ex), int(ey)), 1)

        # Bright leading edge dot.
        hx = cx + self.radius * math.cos(head)
        hy = cy + self.radius * math.sin(head)
        pygame.draw.circle(surface, color, (int(hx), int(hy)), 2)

        # Outer circuit ring — counter-rotating dashes with tick marks.
        ring_spin = -t * 0.25
        seg = 2 * math.pi / self.SEGMENTS
        for s in range(self.SEGMENTS):
            a0 = s * seg + ring_spin
            a1 = a0 + seg * 0.55          # dash covers ~half each slot
            bright = 0.22 + 0.10 * math.sin(t * 2 + s)
            c = tuple(int(v * bright) for v in color)
            pygame.draw.line(
                surface, c,
                (int(cx + self.radius * math.cos(a0)), int(cy + self.radius * math.sin(a0))),
                (int(cx + self.radius * math.cos(a1)), int(cy + self.radius * math.sin(a1))), 1,
            )
            # tick mark pointing inward every 4th segment
            if s % 4 == 0:
                tr = self.radius - 7
                tc = tuple(int(v * 0.3) for v in color)
                pygame.draw.line(
                    surface, tc,
                    (int(cx + self.radius * math.cos(a0)), int(cy + self.radius * math.sin(a0))),
                    (int(cx + tr * math.cos(a0)), int(cy + tr * math.sin(a0))), 1,
                )


class IronHUD:
    """Stark-style holographic HUD: concentric segmented arc rings spinning at
    different rates, a fine tick scale, a center reticle, and corner targeting
    brackets framing the whole overlay."""

    # Outermost rim rings: (radius fraction, [(start_deg, span_deg)...],
    # spin deg/s, line width, brightness). Bold outer ring + thinner arcs just
    # beneath it spinning the opposite way.
    OUTER_RINGS = [
        (1.00, [(8, 70), (130, 100), (255, 40)], 9, 5, 0.7),     # bold anchor ring
        (0.90, [(30, 50), (160, 60), (280, 45)], -20, 1, 0.85),  # thinner, opposite spin, bright
    ]

    def __init__(self, radius):
        self.r = radius

    def _arc(self, surface, color, cx, cy, rr, a0, a1, w=2):
        rect = pygame.Rect(int(cx - rr), int(cy - rr), int(2 * rr), int(2 * rr))
        pygame.draw.arc(surface, color, rect, a0, a1, w)

    def _ring(self, surface, cx, cy, color, chaos, t, spec):
        r_frac, segs, speed, w, bright = spec
        rr = self.r * r_frac
        rot = math.radians(t * speed * (1.0 + chaos * 1.5))
        c = tuple(int(v * bright) for v in color)
        for sdeg, span in segs:
            a0 = math.radians(sdeg) + rot
            self._arc(surface, c, cx, cy, rr, a0, a0 + math.radians(span), w)

    def draw(self, surface, cx, cy, color, chaos, t):
        # ---- OUTERMOST: bold + thin rim rings, sparse cardinal ticks ----
        for spec in self.OUTER_RINGS:
            self._ring(surface, cx, cy, color, chaos, t, spec)

        rt = self.r
        tc = tuple(int(v * 0.4) for v in color)
        for deg in range(0, 360, 30):              # only 12 ticks, longer at 90s
            a = math.radians(deg)
            long = (deg % 90 == 0)
            inner = rt - (12 if long else 6)
            pygame.draw.line(
                surface, tc,
                (int(cx + rt * math.cos(a)), int(cy + rt * math.sin(a))),
                (int(cx + inner * math.cos(a)), int(cy + inner * math.sin(a))),
                2 if long else 1,
            )

        # ---- CENTER: two fixed-length thick arcs sliding up/down their own
        # semicircles, meeting (colliding) at top then bottom ----
        rr = self.r * 0.34
        hs = math.radians(40)                       # fixed half-span (constant length)
        swing = math.sin(t * 1.8) * math.radians(50)
        cc = tuple(int(v * 0.8) for v in color)
        left_c = math.radians(180) - swing
        right_c = math.radians(0) + swing
        self._arc(surface, cc, cx, cy, rr, left_c - hs, left_c + hs, 5)
        self._arc(surface, cc, cx, cy, rr, right_c - hs, right_c + hs, 5)

    def draw_frame(self, surface, color, t):
        """L-shaped corner brackets framing the canvas, plus holo readouts."""
        c = tuple(int(v * 0.4) for v in color)
        m, ln = 12, 26
        w, h = WIDTH, HEIGHT
        corners = [
            (m, m, 1, 1), (w - m, m, -1, 1),
            (m, h - m, 1, -1), (w - m, h - m, -1, -1),
        ]
        for x, y, sx, sy in corners:
            pygame.draw.line(surface, c, (x, y), (x + sx * ln, y), 1)
            pygame.draw.line(surface, c, (x, y), (x, y + sy * ln), 1)


# ---------------------------------------------------------------------------
# Scene — holds the animated elements and draws one frame to a surface
# ---------------------------------------------------------------------------

class _Scene:
    """Owns the organism's parts (membrane, neural mesh, impulses, dust, core)
    and renders one frame onto a surface."""

    CHAOS_MAP = {"idle": 0.0, "listening": 0.85, "processing": 0.5, "speaking": 0.35}
    # How many nerve impulses fire at once, per state.
    IMPULSE_MAP = {"idle": 3, "listening": 10, "processing": 7, "speaking": 8}

    def __init__(self):
        self.sphere_radius = int(WIDTH * 0.22)   # scales with the overlay size
        self.particles = [Particle(self.sphere_radius) for _ in range(NUM_PARTICLES)]
        self.mesh = NeuralMesh(self.sphere_radius)
        self.container_r = int(self.sphere_radius * 1.16)   # clean circle holding the dust
        self.hud = IronHUD(int(self.sphere_radius * 1.62))
        self.core = CoreGlow()
        self.impulses = [Impulse(self.mesh) for _ in range(max(self.IMPULSE_MAP.values()))]
        self.active_impulses = self.IMPULSE_MAP["idle"]

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
        self.active_impulses = self.IMPULSE_MAP.get(state, 3)
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

        # Back to front: container circle -> synaptic mesh -> impulses -> dust
        # -> nucleus (additive, on top so nothing overwrites it into dark
        # streaks) -> Stark HUD (center + rim) -> corner frame + text.
        cr = int(self.container_r + self.pulse * 6)
        pygame.draw.circle(surface, tuple(int(v * 0.5) for v in color), (cx, cy), cr, 2)
        # Ring of small radial ticks surrounding the container.
        tc = tuple(int(v * 0.6) for v in color)
        for deg in range(0, 360, 9):
            a = math.radians(deg)
            ca, sa = math.cos(a), math.sin(a)
            pygame.draw.line(
                surface, tc,
                (int(cx + (cr + 3) * ca), int(cy + (cr + 3) * sa)),
                (int(cx + (cr + 9) * ca), int(cy + (cr + 9) * sa)), 1,
            )

        self.mesh.update(dt, self.chaos, self.pulse)
        self.mesh.draw(surface, cx, cy, color, t)

        for imp in self.impulses[:self.active_impulses]:
            imp.update(dt)
            imp.draw(surface, cx, cy, color)

        for p in self.particles:
            p.update(dt, self.chaos, self.pulse)
            p.draw(surface, cx, cy, color)

        # Nucleus painted last & additively — no element can carve dark lines in it.
        self.core.draw(surface, cx, cy, color, self.pulse, t)

        self.hud.draw(surface, cx, cy, color, self.chaos, t)
        self.hud.draw_frame(surface, color, t)

        self._draw_readouts(surface, cx, cy, color, t)

    def _draw_readouts(self, surface, cx, cy, color, t):
        """Stark-style holographic text labels around the HUD."""
        bright = tuple(int(v * 0.85) for v in color)
        dim = tuple(int(v * 0.45) for v in color)

        # Title, top-left of frame.
        surface.blit(self.title_font.render("J.A.R.V.I.S", True, dim), (20, 16))

        # State, centered under the organism, with a leading marker.
        label = "// " + self.status_text
        ssurf = self.font.render(label, True, bright)
        surface.blit(ssurf, ssurf.get_rect(center=(cx, cy + self.sphere_radius + 52)))

        # Faux telemetry, bottom corners — animated so it feels live.
        load = int(40 + 30 * (math.sin(t * 1.3) * 0.5 + 0.5) + self.chaos * 25)
        hz = int(60 + 18 * math.sin(t * 0.7))
        tl = self.title_font.render(f"SYS {load:02d}%", True, dim)
        tr = self.title_font.render(f"{hz}HZ", True, dim)
        surface.blit(tl, (20, HEIGHT - 28))
        surface.blit(tr, tr.get_rect(topright=(WIDTH - 20, HEIGHT - 28)))


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
