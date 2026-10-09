"""FastAPI application entry point for InfraWatch."""

from fastapi import FastAPI

from app.api.metrics import PrometheusMetrics
from app.api.routes import router
from app.core.monitoring import build_health_monitor


def create_app() -> FastAPI:
    """Create the API and initialize one shared monitoring engine."""
    application = FastAPI(
        title="InfraWatch",
        description="Infrastructure health monitoring and automation system.",
        version="0.1.0",
    )
    monitor = build_health_monitor()
    application.state.health_monitor = monitor
    application.state.log_parser = monitor.log_parser
    application.state.prometheus_metrics = PrometheusMetrics()
    application.include_router(router)

    @application.get("/", tags=["system"])
    def read_root() -> dict[str, str]:
        """Return a minimal service status response."""
        return {"service": "InfraWatch", "status": "foundation-ready"}

    return application


app = create_app()
