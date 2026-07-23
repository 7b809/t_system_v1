# core/logger.py

import logging
import os
from logging.handlers import TimedRotatingFileHandler

from core.config import settings

# Create logs directory if it doesn't exist
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def get_logger(filename: str) -> logging.Logger:
    """
    Returns a configured logger.

    Example:
        logger = get_logger("main")
        logger.info("Application started")

    Log file:
        logs/main.log
    """

    logger = logging.getLogger(filename)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    log_file = os.path.join(LOG_DIR, f"{filename}.log")

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File Handler (Rotates Daily)
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=settings.LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.propagate = False

    return logger
