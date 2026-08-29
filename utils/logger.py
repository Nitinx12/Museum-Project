import logging
import os
from datetime import datetime

# utils/logger.py -> project root is one level up from this file's folder.
_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_UTILS_DIR)


def get_logger(stage: str, name: str) -> logging.Logger:
    valid_stages = ["Mongo Extract", "extraction", "transformation", "loading", "tests"]
    if stage not in valid_stages:
        raise ValueError(
            f"Invalid stage '{stage}'. Must be one of: {valid_stages}"
        )

    # Create <project_root>/logs/<stage>/ folder — resolved from this file's
    # location, not the caller's cwd, so it always lands in the same place
    # no matter which directory the script was run from.
    log_dir = os.path.join(PROJECT_ROOT, "logs", stage)
    os.makedirs(log_dir, exist_ok=True)

    # Log file: logs/<stage>/<name>_2024-06-01_12-00.log
    run_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
    log_file = os.path.join(log_dir, f"{name}_{run_time}.log")

    # Unique logger key per stage+name
    logger_key = f"{stage}.{name}"
    logger     = logging.getLogger(logger_key)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Formatter
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler (INFO and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    # File Handler (DEBUG and above)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger