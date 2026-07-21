import logging
import os

from logging.handlers import TimedRotatingFileHandler
from config.settings import Settings
LOG_DIR = "logs"

os.makedirs(LOG_DIR, exist_ok=True)


# ---------------------------------------------------------
# Console log control
# ---------------------------------------------------------
# If True  -> show logs in CMD only for names in SHOW_LOG_FILE_NAMES
# If False -> do not show any logs in CMD
SHOW_LOGS = Settings.SHOW_LOGS


# Add only the file/module/logger names for which logs should appear in CMD.
#
# Examples:
# If logger is created using:
#     logger = get_logger(__name__)
#
# and __name__ is:
#     api.dashboard_api
#
# then logger_name becomes:
#     dashboard_api
#
# So add "dashboard_api" below.
SHOW_LOG_FILE_NAMES = {
    "candle_builder",
    "repositories",
    "crossover_engine",
}


def get_logger(name: str) -> logging.Logger:
    """
    Creates a logger for each module.

    Example:
        logger = get_logger(__name__)

    Generates file logs like:
        logs/main.log
        logs/upstox_stream.log
        logs/crossover_engine.log
        logs/mongo_app.log

    Console/CMD logs:
        Printed only when SHOW_LOGS = True
        and logger_name is present in SHOW_LOG_FILE_NAMES.
    """

    logger_name = name.split(".")[-1]

    logger = logging.getLogger(logger_name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    log_file = os.path.join(LOG_DIR, f"{logger_name}.log")

    formatter = logging.Formatter(
        fmt=("%(asctime)s | " "%(levelname)s | " "%(name)s | " "%(message)s"),
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ---------------------------------------------------------
    # File handler - always enabled
    # ---------------------------------------------------------
    file_handler = TimedRotatingFileHandler(
        filename=log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )

    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # ---------------------------------------------------------
    # Console/CMD handler - conditionally enabled
    # ---------------------------------------------------------
    if SHOW_LOGS and logger_name in SHOW_LOG_FILE_NAMES:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.propagate = False

    return logger
