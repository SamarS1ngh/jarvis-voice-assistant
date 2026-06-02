#!/usr/bin/env python3
"""J.A.R.V.I.S — Just A Rather Very Intelligent System
Originally: V.O.I.D — Voice Operated Intelligent Daemon
"""

import sys
import signal
import threading

from jarvis_log import log, LOG_PATH
from wake_word import WakeWordDetector
from listener import Listener
from transcriber import Transcriber
from commander import Commander
from speaker import Speaker
from sounds import beep_listening, beep_processing, beep_error
from face_widget import FaceWidget
import config


def main():
    print("=" * 50)
    print("  J.A.R.V.I.S — Just A Rather Very Intelligent System")
    print("=" * 50)
    print(f"  Log file: {LOG_PATH}")
    print()

    log.info("=" * 60)
    log.info("Jarvis starting up")
    log.info(f"Log file: {LOG_PATH}")

    # Load all components
    print("Initializing components...")
    speaker = Speaker()
    listener = Listener()

    print("Loading wake word detector... ", end="", flush=True)
    detector = WakeWordDetector()
    print("done.")

    transcriber = Transcriber()

    commander = Commander()

    if config.GEMINI_API_KEY:
        print("Gemini smart mode: ENABLED")
    else:
        print("Gemini smart mode: DISABLED (set GEMINI_API_KEY in config.py)")

    # The face widget owns the main thread (Qt requirement); the assistant runs
    # in a worker thread.
    face = FaceWidget()
    face.set_state("idle")

    print()
    print(f"Listening for wake word: '{config.WAKE_WORD.replace('_', ' ')}'")
    print("Press Ctrl+C to exit.")
    print()

    def assistant_loop():
        # Speak greeting
        face.set_state("speaking")
        speaker.speak(config.GREETING)
        face.set_state("idle")

        # Main loop — stream mic audio continuously
        print("🔇 Idle — waiting for wake word...")
        for audio_chunk in listener.listen_for_wake_word():
            if not face._running:
                break
            try:
                if detector.detect(audio_chunk):
                    # Wake word detected
                    face.set_state("listening")
                    print("\n🎤 LISTENING — speak your command...")
                    beep_listening()

                    # Record the command
                    audio = listener.record_until_silence()

                    # Done recording
                    face.set_state("processing")
                    beep_processing()
                    print("⚙️  PROCESSING...")

                    if len(audio) == 0:
                        beep_error()
                        face.set_state("speaking")
                        speaker.speak("I didn't hear anything.")
                        face.set_state("idle")
                        print("🔇 Idle — waiting for wake word...")
                        continue

                    # Transcribe
                    text = transcriber.transcribe(audio)
                    print(f"📝 Heard: '{text}'")
                    log.info(f"HEARD: {text!r}")

                    if not text:
                        beep_error()
                        face.set_state("speaking")
                        speaker.speak("I didn't catch that.")
                        face.set_state("idle")
                        print("🔇 Idle — waiting for wake word...")
                        continue

                    # Process command
                    response = commander.process(text)
                    if response:
                        face.set_state("speaking")
                        speaker.speak(response)

                    # Reset detector after processing
                    face.set_state("idle")
                    detector.reset()
                    print("🔇 Idle — waiting for wake word...")

            except Exception as e:
                print(f"Error: {e}")
                log.exception(f"Main loop error: {e}")
                continue

    # Graceful shutdown — stop the Qt loop so run() returns on the main thread.
    def shutdown(sig, frame):
        print("\nShutting down J.A.R.V.I.S...")
        face.quit()

    signal.signal(signal.SIGINT, shutdown)

    threading.Thread(target=assistant_loop, daemon=True).start()

    # Blocks on the main thread, running the overlay event loop.
    face.run()

    speaker.speak("Goodbye.")
    sys.exit(0)


if __name__ == "__main__":
    main()
