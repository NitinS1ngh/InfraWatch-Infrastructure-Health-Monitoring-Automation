"""FastAPI routes for the InfraWatch monitoring engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.api.metrics import PrometheusMetrics
from app.log_parser.log_parser import LogParser
from app.monitoring.health_monitor import HealthMonitor


router = APIRouter(tags=["monitoring"])


@router.get("/health")
def health() -> dict[str, str]:
    """Report that the API process is alive without running monitoring checks."""
    return {"service": "InfraWatch", "status": "ok"}


@router.get("/status")
def status(request: Request) -> Response:
    """Return the coordinator report and map UNHEALTHY to HTTP 503."""
    monitor: HealthMonitor = request.app.state.health_monitor
    report = monitor.collect()
    status_code = 503 if report.get("status") == "UNHEALTHY" else 200
    return Response(
        content=_json_bytes(report),
        status_code=status_code,
        media_type="application/json",
    )


@router.get("/logs")
def logs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Return bounded log counts and recent high-severity entries."""
    parser: LogParser = request.app.state.log_parser
    bounded_parser = LogParser(
        log_path=parser.log_path,
        line_limit=parser.line_limit,
        recent_limit=limit,
    )
    summary = bounded_parser.parse()
    if summary.errors:
        raise HTTPException(
            status_code=503,
            detail="Configured log file could not be read.",
        )
    return {
        "severity_counts": summary.severity_counts,
        "error_count": summary.error_count,
        "critical_count": summary.critical_count,
        "recent_errors": summary.recent_errors,
    }


@router.get("/metrics")
def metrics(request: Request) -> Response:
    """Return Prometheus text metrics from one coordinator report."""
    monitor: HealthMonitor = request.app.state.health_monitor
    exporter: PrometheusMetrics = request.app.state.prometheus_metrics
    report = monitor.collect()
    return Response(
        content=exporter.render(report),
        media_type=CONTENT_TYPE_LATEST,
    )


def _json_bytes(value: dict[str, Any]) -> bytes:
    """Serialize a report without exposing a custom JSON encoder surface."""
    import json

    return json.dumps(value).encode("utf-8")