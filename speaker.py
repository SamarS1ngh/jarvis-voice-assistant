import os
import subprocess

import numpy as np
import sounddevice as sd

import config


class Speaker:
    def __init__(self):
        self._piper_voice = None
        model_path = os.path.join(config.MODELS_DIR, "piper", f"{config.PIPER_VOICE}.onnx")

        try:
            from piper import PiperVoice
            self._piper_voice = PiperVoice.load(model_path)
            self._sample_rate = self._piper_voice.config.sample_rate
            print("TTS: Piper ready.")
        except Exception as e:
            print(f"TTS: Piper failed ({e}), falling back to espeak-ng.")

    def speak(self, text: str):
        if not text:
            return

        print(f"[JARVIS] {text}")

        if self._piper_voice:
            self._speak_piper(text)
        else:
            self._speak_espeak(text)

    def _speak_piper(self, text: str):
        try:
            chunks = []
            for audio_chunk in self._piper_voice.synthesize(text):
                chunks.append(audio_chunk.audio_float_array)
            if not chunks:
                return
            audio = np.concatenate(chunks)
            audio = np.clip(audio, -1.0, 1.0)
            sd.play(audio, samplerate=self._sample_rate)
            sd.wait()
        except Exception as e:
            print(f"Piper TTS error: {e}, falling back to espeak.")
            self._speak_espeak(text)

    def _speak_espeak(self, text: str):
        try:
            subprocess.run(
                ["espeak-ng", "-s", "160", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except Exception as e:
            print(f"espeak error: {e}")
