"""
utils/logger.py
================

Backwards-compatibility shim.

All new code should import from `utils.logging_config` instead:

    from utils.logging_config import get_logger, setup_logging, new_run_id

This module exists so existing import statements like:

    from utils.logger import get_logger

continue to work without any changes in the calling modules.  It
re-exports the new public API and prints one deprecation warning on the
first use so developers are steered toward the new import path.

The deprecated `get_logger(stage, name)` signature is still supported via
a shim inside `logging_config.py`.
"""

from __future__ import annotations

import warnings

from utils.logging_config import (
    get_logger,
    new_run_id,
    setup_logging,
    DEFAULT_LOG_DIR,
    PROJECT_ROOT,
)

# Emit a single DeprecationWarning so static analysis tools flag the old
# import path without breaking anything at runtime.
warnings.warn(
    "import from utils.logger is deprecated; "
    "use 'from utils.logging_config import get_logger' instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "get_logger",
    "new_run_id",
    "setup_logging",
    "DEFAULT_LOG_DIR",
    "PROJECT_ROOT",
]
