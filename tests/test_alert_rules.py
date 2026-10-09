from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import yaml

from app.api.metrics import PrometheusMetrics


RULES_PATH = Path(__file__).parents[1] / "config" / "alerts" / "infra_rules.yml"


def load_alert_rules() -> dict[str, dict]:
    groups = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))["groups"]
    return {
        rule["alert"]: rule
        for group in groups
        for rule in group["rules"]
        if "alert" in rule
    }


def evaluate_synthetic_expression(rule: dict, samples: dict) -> bool:
    """Evaluate the known rule shapes against synthetic samples, not PromQL."""
    expression = rule["expr"]
    if expression.startswith('up{job="infrawatch-api"}'):
        value = samples.get("up")
        return value is not None and value == 0

    required_service = re.fullmatch(
        r'infrawatch_service_availability\{required="true"\} == 0',
        expression,
    )
    if required_service:
        return any(
            labels.get("required") == "true" and value == 0
            for labels, value in samples.get("service_availability", [])
        )

    threshold = re.fullmatch(
        r"(infrawatch_(?:cpu|memory|disk)_utilization_percent) > (\d+)",
        expression,
    )
    if threshold:
        value = samples.get(threshold.group(1))
        return value is not None and value > float(threshold.group(2))

    raise AssertionError(f"unrecognized InfraWatch alert expression: {expression}")


@dataclass
class SyntheticAlertState:
    rule: dict
    pending_since: int | None = None

    def observe(self, samples: dict, elapsed_seconds: int) -> str:
        active = evaluate_synthetic_expression(self.rule, samples)
        if not active:
            self.pending_since = None
            return "inactive"
        if self.pending_since is None:
            self.pending_since = elapsed_seconds
            return "pending"
        required_seconds = int(self.rule["for"].rstrip("sm"))
        if self.rule["for"].endswith("m"):
            required_seconds *= 60
        return "firing" if elapsed_seconds - self.pending_since >= required_seconds else "pending"


def test_alert_rules_reference_exported_metric_families() -> None:
    names = {metric.name for metric in PrometheusMetrics().registry.collect()}
    assert {
        "infrawatch_cpu_utilization_percent",
        "infrawatch_memory_utilization_percent",
        "infrawatch_disk_utilization_percent",
        "infrawatch_service_availability",
    } <= names


def test_api_target_unavailable_and_recovery() -> None:
    rule = load_alert_rules()["InfraWatchAPITargetUnavailable"]
    state = SyntheticAlertState(rule)
    assert state.observe({"up": 0}, 0) == "pending"
    assert state.observe({"up": 0}, 120) == "firing"
    assert state.observe({"up": 1}, 135) == "inactive"


def test_required_service_down_and_recovery() -> None:
    rule = load_alert_rules()["InfraWatchRequiredServiceDown"]
    state = SyntheticAlertState(rule)
    required = ({"service": "required", "required": "true"}, 0)
    assert state.observe({"service_availability": [required]}, 0) == "pending"
    assert state.observe({"service_availability": [required]}, 120) == "firing"
    assert state.observe(
        {"service_availability": [({"service": "required", "required": "true"}, 1)]},
        135,
    ) == "inactive"


def test_optional_service_failure_does_not_trigger_required_alert() -> None:
    rule = load_alert_rules()["InfraWatchRequiredServiceDown"]
    optional = ({"service": "optional", "required": "false"}, 0)
    assert evaluate_synthetic_expression(
        rule,
        {"service_availability": [optional]},
    ) is False


def test_resource_thresholds_use_percentages_and_recover() -> None:
    rules = load_alert_rules()
    cases = {
        "InfraWatchHighCPUUtilization": "infrawatch_cpu_utilization_percent",
        "InfraWatchHighMemoryUtilization": "infrawatch_memory_utilization_percent",
        "InfraWatchHighDiskUtilization": "infrawatch_disk_utilization_percent",
    }
    for alert_name, metric_name in cases.items():
        state = SyntheticAlertState(rules[alert_name])
        assert state.observe({metric_name: 85}, 0) == "inactive"
        assert state.observe({metric_name: 86}, 0) == "pending"
        assert state.observe({metric_name: 86}, 300) == "firing"
        assert state.observe({metric_name: 80}, 315) == "inactive"


def test_missing_metric_data_does_not_create_a_false_positive() -> None:
    rules = load_alert_rules()
    assert evaluate_synthetic_expression(
        rules["InfraWatchHighCPUUtilization"],
        {},
    ) is False
    assert evaluate_synthetic_expression(
        rules["InfraWatchRequiredServiceDown"],
        {},
    ) is False