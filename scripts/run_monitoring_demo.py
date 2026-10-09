"""Run the monitoring engine directly without starting the FastAPI server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.log_parser.log_parser import LogParser
from app.monitoring.health_monitor import HealthMonitor
from app.monitoring.service_checker import ServiceChecker
from app.monitoring.system_metrics import SystemMetricsCollector


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/services.yaml"))
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("tests/fixtures/sample_application.log"),
    )
    args = parser.parse_args()

    monitor = HealthMonitor(
        system_collector=SystemMetricsCollector(),
        service_checker=ServiceChecker.from_yaml(args.config),
        log_parser=LogParser(args.log),
    )
    print(json.dumps(monitor.collect(), indent=2))


if __name__ == "__main__":
    main()