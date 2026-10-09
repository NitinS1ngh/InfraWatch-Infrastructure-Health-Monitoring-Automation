from types import SimpleNamespace
from unittest.mock import patch

from app.monitoring.system_metrics import SystemMetricsCollector


def test_successful_system_metrics_collection() -> None:
    with (
        patch("app.monitoring.system_metrics.psutil.cpu_percent", return_value=15.0),
        patch(
            "app.monitoring.system_metrics.psutil.virtual_memory",
            return_value=SimpleNamespace(percent=48.0, total=1000, used=480, available=520),
        ),
        patch(
            "app.monitoring.system_metrics.psutil.disk_usage",
            return_value=SimpleNamespace(percent=60.0, total=2000, used=1200, free=800),
        ),
        patch("app.monitoring.system_metrics.psutil.boot_time", return_value=1.0),
    ):
        metrics = SystemMetricsCollector(disk_path="/", cpu_interval=0).collect()

    assert metrics.cpu_percent == 15.0
    assert metrics.memory_available_bytes == 520
    assert metrics.disk_free_bytes == 800
    assert metrics.uptime_seconds is not None
    assert metrics.errors == ()