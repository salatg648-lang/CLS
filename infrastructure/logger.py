"""
Logger-Setup — zentraler Logger, von überall importierbar.

    from infrastructure.logger import get_logger
    logger = get_logger(__name__)

Console: INFO+. Datei: alles, rotierend (data/logs/cls.log).
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from infrastructure.paths import LOGS
from config.settings import LOG_BACKUP_COUNT, LOG_MAX_BYTES

LOGS.mkdir(parents=True, exist_ok=True)

_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        LOGS / "cls.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger
