"""Structured (JSON) logging for CineMind.

Render and other log aggregators ingest each stdout line as one event; JSON
keeps them queryable (search by ``level``, ``name``, ``message``). Enabled
with ``LOG_FORMAT=json``; the default ``human`` format stays readable for
local development.
"""

import json
import logging
import sys

from app.core.config import get_settings


class JsonFormatter(logging.Formatter):
    """Format every record as a single-line JSON object."""

    _BASE_ATTRS = frozenset(
        vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Extra keys passed via ``logger.info("...", extra={...})``.
        for key, value in record.__dict__.items():
            if key not in self._BASE_ATTRS and key not in {"message", "asctime"}:
                payload.setdefault(key, value)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Install the formatter chosen by LOG_FORMAT on all loggers."""
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
