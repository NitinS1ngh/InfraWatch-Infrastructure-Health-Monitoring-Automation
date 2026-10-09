from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def test_grafana_environment_example_uses_official_variable_names() -> None:
    environment = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "GF_SECURITY_ADMIN_USER=admin" in environment
    assert "GF_SECURITY_ADMIN_PASSWORD=change-me-local-only" in environment
    assert "GRAFANA_ADMIN_USER" not in environment
    assert "GRAFANA_ADMIN_PASSWORD" not in environment


def test_compose_loads_the_noncommitted_environment_file() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "- .env" in compose
    assert ".env" in gitignore
    assert "!.env.example" in gitignore