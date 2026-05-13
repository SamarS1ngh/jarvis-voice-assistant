"""Centralized logger for Jarvis. Writes to project_dir/jarvis.log.

Captures the full pipeline:
  - heard text (Whisper output)
  - which handler matched (or fell through to Gemini)
  - Gemini's raw response and parsed action
  - executed shell commands
  - screenshots taken
  - final spoken response
  - errors

Use:
    from jarvis_log import log
    log.info(...)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

import config


LOG_PATH = os.path.join(config.PROJECT_DIR, "jarvis.log")

log = logging.getLogger("jarvis")

if not log.handlers:
    log.setLevel(logging.DEBUG)
    log.propagate = False

    fh = RotatingFileHandler(
        LOG_PATH,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    log.addHandler(fh)
