from pathlib import Path
import re

import yaml


PROJECT_ROOT = Path(__file__).parents[1]
PROMETHEUS_CONFIG = PROJECT_ROOT / "config" / "prometheus" / "prometheus.yml"
RULES_CONFIG = PROJECT_ROOT / "config" / "alerts" / "infra_rules.yml"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def duration_seconds(value: str) -> int:
    match = re.fullmatch(r"(\d+)([smhd])", value)
    assert match, f"unsupported duration: {value}"
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return int(match.group(1)) * units[match.group(2)]


def test_prometheus_config_exists_and_has_valid_intervals() -> None:
    config = load_yaml(PROMETHEUS_CONFIG)
    assert duration_seconds(config["global"]["scrape_interval"]) == 15
    assert duration_seconds(config["global"]["scrape_timeout"]) < 15
    assert duration_seconds(config["global"]["evaluation_interval"]) == 15
    assert config["rule_files"] == ["/etc/prometheus/infra_rules.yml"]


def test_prometheus_self_scrape_and_infrawatch_target() -> None:
    jobs = {job["job_name"]: job for job in load_yaml(PROMETHEUS_CONFIG)["scrape_configs"]}
    assert "prometheus" in jobs
    assert jobs["prometheus"]["static_configs"][0]["targets"] == ["localhost:9090"]

    api_job = jobs["infrawatch-api"]
    assert api_job["metrics_path"] == "/metrics"
    assert api_job["static_configs"][0]["targets"] == ["api:8000"]
    assert duration_seconds(api_job["scrape_timeout"]) < duration_seconds(
        api_job["scrape_interval"]
    )


def load_compose() -> dict:
    return yaml.safe_load(
        (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )


def test_compose_contains_api_and_prometheus_services() -> None:
    compose = load_compose()
    assert set(compose["services"]) == {"api", "prometheus", "grafana", "recovery-worker"}
    assert compose["services"]["prometheus"]["image"] == "prom/prometheus:v2.55.1"


def test_compose_prometheus_mounts_and_port() -> None:
    compose = load_compose()
    prometheus = compose["services"]["prometheus"]
    assert prometheus["ports"] == [
        "${INFRAWATCH_BIND_ADDRESS:-127.0.0.1}:${INFRAWATCH_PROMETHEUS_PORT:-9090}:9090"
    ]
    assert "./config/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro" in prometheus["volumes"]
    assert "./config/alerts/infra_rules.yml:/etc/prometheus/infra_rules.yml:ro" in prometheus["volumes"]
    assert "prometheus_data:/prometheus" in prometheus["volumes"]
    assert "prometheus_data" in compose["volumes"]


def test_compose_dependency_and_healthcheck() -> None:
    compose = load_compose()
    services = compose["services"]
    assert services["prometheus"]["depends_on"]["api"]["condition"] == "service_healthy"
    healthcheck = services["prometheus"]["healthcheck"]["test"]
    assert healthcheck[0:2] == ["CMD", "wget"]
    assert "/-/ready" in healthcheck[-1]
    assert services["api"]["ports"] == [
        "${INFRAWATCH_BIND_ADDRESS:-127.0.0.1}:${INFRAWATCH_API_PORT:-8000}:8000"
    ]


def test_alert_rules_reference_exported_metrics_and_have_metadata() -> None:
    groups = load_yaml(RULES_CONFIG)["groups"]
    alert_rules = [
        rule
        for group in groups
        for rule in group["rules"]
        if "alert" in rule
    ]
    assert len(alert_rules) == 5

    exported_metrics = (
        "up",
        "infrawatch_service_availability",
        "infrawatch_cpu_utilization_percent",
        "infrawatch_memory_utilization_percent",
        "infrawatch_disk_utilization_percent",
    )
    for rule in alert_rules:
        assert any(metric in rule["expr"] for metric in exported_metrics)
        assert rule["labels"]["severity"] in {"warning", "critical"}
        assert rule["annotations"]["summary"]
        assert rule["annotations"]["description"]
        assert duration_seconds(rule["for"]) >= 120


def test_recording_rules_reference_exported_metrics() -> None:
    recording_rules = [
        rule
        for group in load_yaml(RULES_CONFIG)["groups"]
        for rule in group["rules"]
        if "record" in rule
    ]
    assert len(recording_rules) == 3
    assert all(
        rule["expr"]
        in {
            "infrawatch_cpu_utilization_percent",
            "infrawatch_memory_utilization_percent",
            "infrawatch_disk_utilization_percent",
        }
        for rule in recording_rules
    )