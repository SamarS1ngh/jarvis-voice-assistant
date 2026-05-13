import numpy as np
import sounddevice as sd


def beep(frequency=800, duration=0.15, volume=0.3):
    """Play a short beep sound."""
    sample_rate = 22050
    t = np.linspace(0, duration, int(sample_rate * duration), dtype=np.float32)
    tone = volume * np.sin(2 * np.pi * frequency * t)
    # Fade in/out to avoid clicks
    fade = int(sample_rate * 0.01)
    tone[:fade] *= np.linspace(0, 1, fade)
    tone[-fade:] *= np.linspace(1, 0, fade)
    sd.play(tone, samplerate=sample_rate)
    sd.wait()


def beep_listening():
    """High beep — wake word detected, now listening."""
    beep(frequency=1000, duration=0.15)


def beep_processing():
    """Low beep — done recording, now processing."""
    beep(frequency=600, duration=0.1)


def beep_error():
    """Two short low beeps — error or didn't understand."""
    beep(frequency=400, duration=0.1)
    beep(frequency=400, duration=0.1)
