"""Collect host-level metrics with psutil."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import psutil


@dataclass(frozen=True)
class SystemMetrics:
    """A snapshot of host metrics and any collection errors."""

    timestamp: str
    cpu_percent: float | None
    memory_percent: float | None
    memory_total_bytes: int | None
    memory_used_bytes: int | None
    memory_available_bytes: int | None
    disk_percent: float | None
    disk_total_bytes: int | None
    disk_used_bytes: int | None
    disk_free_bytes: int | None
    uptime_seconds: float | None
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation of this snapshot."""
        result = asdict(self)
        result["errors"] = list(self.errors)
        return result


class SystemMetricsCollector:
    """Collect system metrics for a configurable filesystem path."""

    def __init__(self, disk_path: str = "/", cpu_interval: float = 0.1) -> None:
        if cpu_interval < 0:
            raise ValueError("cpu_interval must be non-negative")
        self.disk_path = disk_path
        self.cpu_interval = cpu_interval

    def collect(self) -> SystemMetrics:
        """Collect one snapshot while preserving partial results on failures."""
        errors: list[str] = []
        timestamp = datetime.now(timezone.utc).isoformat()

        cpu_percent: float | None = None
        try:
            cpu_percent = float(psutil.cpu_percent(interval=self.cpu_interval))
        except Exception as exc:
            errors.append(f"cpu collection failed: {exc}")

        memory_percent: float | None = None
        memory_total: int | None = None
        memory_used: int | None = None
        memory_available: int | None = None
        try:
            memory = psutil.virtual_memory()
            memory_percent = float(memory.percent)
            memory_total = int(memory.total)
            memory_used = int(memory.used)
            memory_available = int(memory.available)
        except Exception as exc:
            errors.append(f"memory collection failed: {exc}")

        disk_percent: float | None = None
        disk_total: int | None = None
        disk_used: int | None = None
        disk_free: int | None = None
        try:
            disk = psutil.disk_usage(self.disk_path)
            disk_percent = float(disk.percent)
            disk_total = int(disk.total)
            disk_used = int(disk.used)
            disk_free = int(disk.free)
        except Exception as exc:
            errors.append(f"disk collection failed for {self.disk_path}: {exc}")

        uptime_seconds: float | None = None
        try:
            uptime_seconds = max(0.0, datetime.now().timestamp() - psutil.boot_time())
        except Exception as exc:
            errors.append(f"uptime collection failed: {exc}")

        return SystemMetrics(
            timestamp=timestamp,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            memory_total_bytes=memory_total,
            memory_used_bytes=memory_used,
            memory_available_bytes=memory_available,
            disk_percent=disk_percent,
            disk_total_bytes=disk_total,
            disk_used_bytes=disk_used,
            disk_free_bytes=disk_free,
            uptime_seconds=uptime_seconds,
            errors=tuple(errors),
        )