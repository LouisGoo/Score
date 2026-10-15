"""Minimal error logs without request data or exception messages."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


class ErrorFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage() if record.name.startswith("score.") else "runtime_error",
        }
        for key in ("request_id", "status", "error_type"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        if hasattr(record, "frames"):
            data["frames"] = record.frames
        return json.dumps(data, ensure_ascii=False)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(ErrorFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.ERROR)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
        logger.setLevel(logging.ERROR)


def log_failure(logger, event, error, **context):
    # Never retain exception objects, messages, locals or source text.
    frames = []
    tb = error.__traceback__
    while tb:
        frames.append(
            {
                "file": Path(tb.tb_frame.f_code.co_filename).name,
                "function": tb.tb_frame.f_code.co_name,
                "line": tb.tb_lineno,
            }
        )
        tb = tb.tb_next
    logger.error(
        event,
        extra={
            **context,
            "error_type": type(error).__name__,
            "frames": frames,
        },
    )
