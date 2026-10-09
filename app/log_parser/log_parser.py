"""Bounded, read-only application log parsing."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any


LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LEVEL_PATTERN = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")


@dataclass(frozen=True)
class LogSummary:
    """Severity counts and recent high-severity entries."""

    path: str
    severity_counts: dict[str, int]
    error_count: int
    critical_count: int
    recent_errors: list[str]
    errors: tuple[str, ...] = ()
    missing: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["errors"] = list(self.errors)
        return result


class LogParser:
    """Parse at most ``line_limit`` lines while keeping memory bounded."""

    def __init__(
        self,
        log_path: str | Path,
        line_limit: int = 1000,
        recent_limit: int = 20,
    ) -> None:
        if line_limit <= 0 or recent_limit < 0:
            raise ValueError("line_limit must be positive and recent_limit non-negative")
        self.log_path = Path(log_path)
        self.line_limit = line_limit
        self.recent_limit = recent_limit

    def parse(self) -> LogSummary:
        """Parse the most recent bounded window of a log file."""
        counts = Counter({level: 0 for level in LOG_LEVELS})
        recent_entries: deque[str] = deque(maxlen=self.recent_limit)
        errors: list[str] = []
        missing = False
        try:
            if not self.log_path.is_file():
                missing = True
                raise FileNotFoundError(self.log_path)
            with self.log_path.open("r", encoding="utf-8", errors="replace") as log_file:
                lines = deque(log_file, maxlen=self.line_limit)
            for line in lines:
                match = LEVEL_PATTERN.search(line)
                if not match:
                    continue
                level = match.group(1)
                counts[level] += 1
                if level in {"ERROR", "CRITICAL"} and self.recent_limit:
                    recent_entries.append(line.rstrip("\n"))
        except (OSError, UnicodeError) as exc:
            errors.append(f"unable to read log file {self.log_path}: {exc}")

        return LogSummary(
            path=str(self.log_path),
            severity_counts=dict(counts),
            error_count=counts["ERROR"],
            critical_count=counts["CRITICAL"],
            recent_errors=list(recent_entries),
            errors=tuple(errors),
            missing=missing,
        )