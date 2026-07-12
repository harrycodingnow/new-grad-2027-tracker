"""Typed source failures so health reporting can distinguish causes."""

from __future__ import annotations


class SourceError(Exception):
    """A source failed in a way that should be recorded, not crash the run."""

    category = "network_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NetworkError(SourceError):
    category = "network_error"


class BlockedError(SourceError):
    category = "blocked"


class ParseError(SourceError):
    category = "parse_error"


class InvalidConfigError(SourceError):
    category = "invalid_config"


class StructureChangedError(SourceError):
    category = "structure_changed"


class UnsupportedSourceError(SourceError):
    category = "unsupported"
