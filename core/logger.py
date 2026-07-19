import logging
import os

from logging.handlers import TimedRotatingFileHandler


LOG_DIR = "logs"

os.makedirs(LOG_DIR, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """
    Creates a logger for each module.

    Example:
        logger = get_logger(__name__)

    Generates:
        logs/main.log
        logs/upstox_stream.log
        logs/crossover_engine.log
        logs/mongo_app.log
    """

    logger_name = name.split(".")[-1]

    logger = logging.getLogger(logger_name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    log_file = os.path.join(
        LOG_DIR,
        f"{logger_name}.log"
    )

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )

    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.propagate = False

    return logger