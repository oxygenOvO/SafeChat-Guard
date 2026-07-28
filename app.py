"""Compatibility launcher for the canonical SafeChat-Guard HTTP API.

Use ``python api_server.py`` for the documented production entry point.
"""

from api_server import (
    SafeChatApiHandler,
    create_server,
    main,
    pipeline,
)


# Preserve the historical import name without maintaining a second API stack.
SafeChatHandler = SafeChatApiHandler


__all__ = [
    "SafeChatHandler",
    "SafeChatApiHandler",
    "create_server",
    "main",
    "pipeline",
]


if __name__ == "__main__":
    main()
