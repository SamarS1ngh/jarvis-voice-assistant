import numpy as np
from openwakeword.model import Model
import config


class WakeWordDetector:
    def __init__(self):
        # Load with default pre-trained models (includes "hey_jarvis" and others)
        self.model = Model()
        self.threshold = config.WAKE_WORD_THRESHOLD

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """Check if wake word is present in audio chunk.

        Args:
            audio_chunk: numpy array of int16 audio samples (1280 samples = 80ms at 16kHz)

        Returns:
            True if wake word detected above threshold.
        """
        prediction = self.model.predict(audio_chunk)
        for model_name in self.model.prediction_buffer.keys():
            scores = list(self.model.prediction_buffer[model_name])
            if scores and scores[-1] > self.threshold:
                self.model.reset()
                return True
        return False

    def reset(self):
        self.model.reset()
