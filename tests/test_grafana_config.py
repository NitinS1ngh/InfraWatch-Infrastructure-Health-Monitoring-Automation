from pathlib import Path
import json
import re

import yaml


PROJECT_ROOT = Path(__file__).parents[1]
DATASOURCE_PATH = PROJECT_ROOT / "config/grafana/provisioning/datasources/prometheus.yml"
PROVIDER_PATH = PROJECT_ROOT / "config/grafana/provisioning/dashboards/infrawatch.yml"
DASHBOARD_PATH = PROJECT_ROOT / "config/grafana/dashboards/infrawatch-overview.json"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_compose() -> dict:
    return load_yaml(PROJECT_ROOT / "docker-compose.yml")


def test_compose_contains_pinned_grafana_service() -> None:
    grafana = load_compose()["services"]["grafana"]
    assert re.fullmatch(r"grafana/grafana:\d+\.\d+\.\d+", grafana["image"])
    assert grafana["ports"] == [
        "${INFRAWATCH_BIND_ADDRESS:-127.0.0.1}:${INFRAWATCH_GRAFANA_PORT:-3000}:3000"
    ]
    assert "grafana_data:/var/lib/grafana" in grafana["volumes"]


def test_grafana_depends_on_prometheus_and_has_healthcheck() -> None:
    grafana = load_compose()["services"]["grafana"]
    assert grafana["depends_on"]["prometheus"]["condition"] == "service_healthy"
    healthcheck = grafana["healthcheck"]["test"]
    assert healthcheck[0:2] == ["CMD", "wget"]
    assert "/api/health" in healthcheck[-1]


def test_grafana_provisioning_mounts_match_files() -> None:
    grafana = load_compose()["services"]["grafana"]
    assert "./config/grafana/provisioning:/etc/grafana/provisioning:ro" in grafana["volumes"]
    assert "./config/grafana/dashboards:/var/lib/grafana/dashboards:ro" in grafana["volumes"]
    assert DATASOURCE_PATH.is_file()
    assert PROVIDER_PATH.is_file()
    assert DASHBOARD_PATH.is_file()


def test_datasource_uses_internal_prometheus_and_is_default() -> None:
    datasource = load_yaml(DATASOURCE_PATH)
    entry = datasource["datasources"][0]
    assert entry["name"] == "Prometheus"
    assert entry["uid"] == "Prometheus"
    assert entry["type"] == "prometheus"
    assert entry["url"] == "http://prometheus:9090"
    assert entry["isDefault"] is True


def test_dashboard_provider_uses_container_dashboard_path() -> None:
    provider = load_yaml(PROVIDER_PATH)["providers"][0]
    assert provider["type"] == "file"
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"


def test_dashboard_json_has_required_unique_panels() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    panels = dashboard["panels"]
    panel_ids = [panel["id"] for panel in panels]
    titles = {panel["title"] for panel in panels}
    required_titles = {
        "CPU Utilization",
        "Memory Utilization",
        "Disk Utilization",
        "System Uptime",
        "Monitored Service Availability",
        "Service Response Time",
        "Application Error and Critical Logs",
        "Prometheus Scrape Health",
        "Active Prometheus Alerts",
    }
    assert len(panel_ids) == len(set(panel_ids))
    assert required_titles <= titles


def test_dashboard_queries_reference_exported_or_prometheus_metrics() -> None:
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    queries = [
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    known_metrics = (
        "infrawatch_cpu_utilization_percent",
        "infrawatch_memory_utilization_percent",
        "infrawatch_disk_utilization_percent",
        "infrawatch_system_uptime_seconds",
        "infrawatch_service_availability",
        "infrawatch_service_response_time_milliseconds",
        "infrawatch_log_severity_count",
        "up",
        "ALERTS",
    )
    assert all(any(metric in query for metric in known_metrics) for query in queries)
    assert any('{{service}}' in panel["targets"][0].get("legendFormat", "") for panel in dashboard["panels"])


def test_grafana_configuration_does_not_commit_credentials() -> None:
    tracked_config = [
        (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8"),
        DATASOURCE_PATH.read_text(encoding="utf-8"),
        PROVIDER_PATH.read_text(encoding="utf-8"),
        DASHBOARD_PATH.read_text(encoding="utf-8"),
    ]
    combined = "\n".join(tracked_config)
    assert "admin_password:" not in combined
    assert "GF_SECURITY_ADMIN_PASSWORD:" not in combined
    assert "change-me-local-only" not in combined
    assert ".env" in load_compose()["services"]["grafana"]["env_file"]