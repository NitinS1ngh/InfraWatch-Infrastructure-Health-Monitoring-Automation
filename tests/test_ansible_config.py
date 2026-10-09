from pathlib import Path
import re

import yaml


PROJECT_ROOT = Path(__file__).parents[1]
ANSIBLE_ROOT = PROJECT_ROOT / "ansible"


def read(path: str) -> str:
    return (ANSIBLE_ROOT / path).read_text(encoding="utf-8")


def test_expected_playbooks_and_role_tasks_exist() -> None:
    for path in (
        "ansible.cfg",
        "inventory/group_vars/all.yml",
        "inventory/local.yml",
        "playbooks/site.yml",
        "playbooks/deploy.yml",
        "playbooks/verify.yml",
        "roles/prerequisites/tasks/main.yml",
        "roles/configuration/tasks/main.yml",
        "roles/deployment/tasks/main.yml",
        "roles/verification/tasks/main.yml",
    ):
        assert (ANSIBLE_ROOT / path).is_file(), path


def test_ansible_config_uses_core_compatible_relative_roles_path() -> None:
    config = read("ansible.cfg")
    assert "roles_path = roles" in config
    assert "%(config_dir)s" not in config
    assert "roles_path = ./ansible/roles" not in config
    roles_root = ANSIBLE_ROOT / "roles"
    assert (roles_root / "prerequisites").is_dir()
    assert (roles_root / "prerequisites" / "tasks" / "main.yml").is_file()
    assert (roles_root / "verification").is_dir()
    assert (roles_root / "verification" / "tasks" / "main.yml").is_file()


def test_inventory_is_explicitly_local_and_does_not_enable_become() -> None:
    inventory = yaml.safe_load(read("inventory/local.yml"))
    host = inventory["all"]["children"]["infrawatch_targets"]["hosts"]["local"]
    assert host["ansible_connection"] == "local"
    assert host["ansible_host"] == "127.0.0.1"
    assert host["ansible_become"] is False
    assert inventory["all"]["vars"]["ansible_become"] is False


def test_playbooks_have_explicit_execution_modes() -> None:
    site = yaml.safe_load(read("playbooks/site.yml"))[0]["vars"]
    deploy = yaml.safe_load(read("playbooks/deploy.yml"))[0]["vars"]
    verify = yaml.safe_load(read("playbooks/verify.yml"))[0]["vars"]
    assert site["infrawatch_start_services"] is False
    assert site["infrawatch_manage_configuration"] is False
    assert deploy["infrawatch_start_services"] is True
    assert deploy["infrawatch_manage_configuration"] is True
    assert verify["infrawatch_verify_services"] is True
    assert site["infrawatch_validate_compose"] is False
    assert deploy["infrawatch_validate_compose"] is True


def test_prerequisites_fail_clearly_when_deployment_tools_are_missing() -> None:
    tasks = read("roles/prerequisites/tasks/main.yml")
    assert "docker --version" in tasks
    assert "docker compose version" in tasks
    assert "infrawatch_require_docker" in tasks
    assert "required for deployment" in tasks


def test_deployment_validates_and_uses_existing_compose_file() -> None:
    tasks = read("roles/deployment/tasks/main.yml")
    assert "docker-compose.yml" in tasks
    assert "config" in tasks
    assert "infrawatch_start_services" in tasks
    assert "docker" in tasks and "compose" in tasks and "up" in tasks
    assert "infrawatch_compose_project_name" in tasks
    assert "INFRAWATCH_API_PORT" in tasks
    assert "slurp" in tasks
    assert "b64decode" in tasks
    assert "INFRAWATCH_RECOVERY_DRY_RUN=true" in tasks
    assert "INFRAWATCH_DOCKER_RECOVERY_ENABLED=false" in tasks


def test_verification_uses_expected_endpoints_and_bounded_retries() -> None:
    tasks = read("roles/verification/tasks/main.yml")
    for endpoint in (
        "infrawatch_api_health_url",
        "infrawatch_api_status_url",
        "infrawatch_prometheus_ready_url",
        "infrawatch_grafana_health_url",
    ):
        assert endpoint in tasks
    assert "retries: \"{{ infrawatch_verify_retries }}\"" in tasks
    assert "delay: \"{{ infrawatch_verify_delay }}\"" in tasks
    assert "status_code: [200, 503]" in tasks


def test_shared_defaults_bound_retries_and_define_health_urls() -> None:
    defaults = yaml.safe_load(read("inventory/group_vars/all.yml"))
    assert defaults["infrawatch_verify_retries"] <= 5
    assert defaults["infrawatch_verify_delay"] <= 10
    assert defaults["infrawatch_api_health_url"].endswith("/health")
    assert defaults["infrawatch_api_status_url"].endswith("/status")
    assert defaults["infrawatch_prometheus_ready_url"].endswith("/-/ready")
    assert defaults["infrawatch_grafana_health_url"].endswith("/api/health")


def test_ansible_files_contain_no_credentials_or_private_keys() -> None:
    contents = "\n".join(
        path.read_text(encoding="utf-8")
        for path in ANSIBLE_ROOT.rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    )
    assert not re.search(r"-----BEGIN .*PRIVATE KEY-----", contents)
    assert "password:" not in contents.lower()
    assert "GRAFANA_ADMIN_PASSWORD" not in contents