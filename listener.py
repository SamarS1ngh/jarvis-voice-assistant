import numpy as np
import sounddevice as sd
import queue
import config


class Listener:
    def __init__(self):
        self.sample_rate = config.SAMPLE_RATE
        self.channels = config.CHANNELS
        self.silence_threshold = config.SILENCE_THRESHOLD
        self.silence_duration = config.SILENCE_DURATION
        self.max_duration = config.MAX_RECORD_SECONDS
        self.chunk_size = config.CHUNK_SIZE
        self._queue = queue.Queue()

    def _audio_callback(self, indata, frames, time_info, status):
        self._queue.put(indata.copy())

    def listen_for_wake_word(self):
        """Yield audio chunks continuously for wake word detection.

        Yields:
            numpy array of int16 audio (CHUNK_SIZE samples).
        """
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_size,
            callback=self._audio_callback,
        ):
            while True:
                chunk = self._queue.get()
                yield chunk.flatten()

    def record_until_silence(self) -> np.ndarray:
        """Record audio from mic until silence is detected.

        Returns:
            numpy array of float32 audio samples.
        """
        frames = []
        silent_chunks = 0
        chunk_duration = 0.1  # 100ms chunks
        chunk_samples = int(self.sample_rate * chunk_duration)
        max_chunks = int(self.max_duration / chunk_duration)
        silence_chunks_needed = int(self.silence_duration / chunk_duration)

        rec_queue = queue.Queue()

        def callback(indata, frames_count, time_info, status):
            rec_queue.put(indata.copy())

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=chunk_samples,
            callback=callback,
        ):
            for _ in range(max_chunks):
                chunk = rec_queue.get()
                frames.append(chunk)

                rms = np.sqrt(np.mean(chunk**2))
                if rms < self.silence_threshold:
                    silent_chunks += 1
                else:
                    silent_chunks = 0

                if silent_chunks >= silence_chunks_needed and len(frames) > silence_chunks_needed:
                    break

        if not frames:
            return np.array([], dtype="float32")

        audio = np.concatenate(frames, axis=0).flatten()
        return audio
