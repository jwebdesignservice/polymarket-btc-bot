"""
logger.py — Structured logging to file + console with timestamps.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from config import config


_LOG_FORMAT = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-20s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_root_logger():
    root = logging.getLogger()
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    root.setLevel(level)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(ch)

    # Rotating file handler (10 MB × 5 backups)
    fh = RotatingFileHandler(config.log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(fh)


_setup_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a named child logger."""
    return logging.getLogger(name)
