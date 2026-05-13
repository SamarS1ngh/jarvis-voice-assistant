import numpy as np
from faster_whisper import WhisperModel
import config


class Transcriber:
    def __init__(self):
        print(f"Loading Whisper model ({config.WHISPER_MODEL})... ", end="", flush=True)
        self.model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
        print("done.")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio to text.

        Args:
            audio: numpy array of float32 audio samples at 16kHz.

        Returns:
            Transcribed text string, lowercased and stripped.
        """
        if len(audio) == 0:
            return ""

        segments, _ = self.model.transcribe(
            audio,
            beam_size=5,
            language=config.WHISPER_LANGUAGE,
            vad_filter=True,
        )
        text = " ".join(seg.text for seg in segments).strip().lower()
        return text
