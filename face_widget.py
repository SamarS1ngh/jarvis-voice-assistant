"""Floating AI face widget — an animated sphere of brainwave particles.

States:
  idle       — slow, smooth orbital motion (dim cyan glow)
  listening  — fast, chaotic motion (bright green pulses)
  processing — medium speed, swirling inward (orange/amber)
  speaking   — rhythmic expansion pulses (bright cyan)
"""

import math
import random
import threading
import time

import pygame

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 400, 400
FPS = 60
BG_COLOR = (10, 10, 18)

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
# Main widget class
# ---------------------------------------------------------------------------

class FaceWidget:
    """Thread-safe animated AI face widget.

    Call set_state("idle" | "listening" | "processing" | "speaking") from any
    thread to change the animation.  Call stop() to close the window.
    """

    def __init__(self):
        self._state = "idle"
        self._target_state = "idle"
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

        self.sphere_radius = 80
        self._chaos = 0.0          # current chaos amount (0..1)
        self._target_chaos = 0.0
        self._pulse = 0.0          # breathing pulse
        self._status_text = "IDLE"

    # -- public API (thread-safe) ------------------------------------------

    def set_state(self, state: str):
        with self._lock:
            self._target_state = state

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # -- main loop (runs in its own thread) ---------------------------------

    def _run(self):
        pygame.init()
        screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("JARVIS")
        clock = pygame.time.Clock()

        cx, cy = WIDTH // 2, HEIGHT // 2

        particles = [Particle(self.sphere_radius) for _ in range(NUM_PARTICLES)]
        tendrils = [Tendril(self.sphere_radius, i, NUM_TENDRILS) for i in range(NUM_TENDRILS)]
        core = CoreGlow()

        font = pygame.font.SysFont("monospace", 14, bold=True)
        title_font = pygame.font.SysFont("monospace", 11)

        current_color = PALETTE["idle"]
        target_color = PALETTE["idle"]

        chaos_map = {
            "idle": 0.0,
            "listening": 0.85,
            "processing": 0.5,
            "speaking": 0.35,
        }

        while self._running:
            dt = clock.tick(FPS) / 1000.0
            t = time.time()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._running = False
                    break

            # Read target state
            with self._lock:
                new_state = self._target_state

            if new_state != self._state:
                self._state = new_state
                target_color = PALETTE.get(self._state, PALETTE["idle"])
                self._target_chaos = chaos_map.get(self._state, 0.0)
                self._status_text = self._state.upper()

            # Smooth transitions
            lerp_speed = 3.0 * dt
            current_color = _lerp_color(current_color, target_color, min(1, lerp_speed))
            self._chaos = _lerp(self._chaos, self._target_chaos, min(1, lerp_speed * 1.5))

            # Breathing pulse
            if self._state == "speaking":
                self._pulse = math.sin(t * 6) * 0.5 + 0.5
            elif self._state == "listening":
                self._pulse = math.sin(t * 4) * 0.3 + math.sin(t * 7) * 0.2
            elif self._state == "processing":
                self._pulse = math.sin(t * 8) * 0.15
            else:
                self._pulse = math.sin(t * 1.5) * 0.1

            # --- Draw ---
            screen.fill(BG_COLOR)

            # Core glow
            core.draw(screen, cx, cy, current_color, self._pulse)

            # Tendrils
            for tendril in tendrils:
                tendril.draw(screen, cx, cy, current_color, self._chaos, self._pulse, t)

            # Particles
            for p in particles:
                p.update(dt, self._chaos, self._pulse)
                p.draw(screen, cx, cy, current_color)

            # Outer ring
            ring_radius = int(self.sphere_radius + 20 + self._pulse * 12)
            ring_color = tuple(int(v * 0.15) for v in current_color)
            pygame.draw.circle(screen, ring_color, (cx, cy), ring_radius, 1)

            # Inner ring
            inner_r = int(self.sphere_radius * 0.6 + self._pulse * 5)
            inner_c = tuple(int(v * 0.1) for v in current_color)
            pygame.draw.circle(screen, inner_c, (cx, cy), inner_r, 1)

            # Status text
            status_surf = font.render(self._status_text, True, current_color)
            sr = status_surf.get_rect(center=(cx, cy + self.sphere_radius + 45))
            screen.blit(status_surf, sr)

            # Title
            title_surf = title_font.render("J.A.R.V.I.S", True, tuple(int(v * 0.4) for v in current_color))
            tr = title_surf.get_rect(center=(cx, cy - self.sphere_radius - 40))
            screen.blit(title_surf, tr)

            pygame.display.flip()

        pygame.quit()


# ---------------------------------------------------------------------------
# Standalone demo — cycle through states
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    widget = FaceWidget()
    widget.start()

    try:
        states = ["idle", "listening", "processing", "speaking"]
        idx = 0
        while True:
            time.sleep(3)
            idx = (idx + 1) % len(states)
            print(f"-> {states[idx]}")
            widget.set_state(states[idx])
    except KeyboardInterrupt:
        widget.stop()
