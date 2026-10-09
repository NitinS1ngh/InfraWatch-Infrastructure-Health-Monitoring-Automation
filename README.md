# InfraWatch

InfraWatch is an infrastructure health monitoring and automation system. It will provide a FastAPI REST API, collect operational metrics with Prometheus, present dashboards in Grafana, and use Ansible for configuration management and deployment.

## Planned architecture

- `app/api/`: REST API routes and request/response models.
- `app/monitoring/`: system and service metric collection.
- `app/log_parser/`: log ingestion and parsing components.
- `app/core/`: shared configuration and application services.
- `config/`: Prometheus, Grafana, and alerting configuration.
- `ansible/`: inventories, playbooks, and reusable roles.
- `tests/`: pytest tests.
- `scripts/`: local development and operational helpers.
- `logs/`: local runtime logs; generated contents are ignored by Git.

The current implementation includes the monitoring engine, a local-development FastAPI integration, Prometheus scrape/rule configuration, Grafana dashboards, and Ansible deployment automation. External alert delivery remains a later step.

## Architecture diagram


flowchart TB
    subgraph HOST["Monitored Host"]
        SYS["System Metrics<br/>CPU · Memory · Disk · Uptime"]
        SVC["Configured Service Checks<br/>HTTP / HTTPS"]
        LOG["Log Parser<br/>Severity Counts"]
    end

    subgraph CORE["InfraWatch · Python"]
        MON["Health Monitor"]
        API["FastAPI REST API<br/>/health · /status · /logs · /metrics"]
        POLICY["Recovery Manager<br/>Allowlist · Retry · Cooldown · Timeout"]
        WORKER["Optional Recovery Worker<br/>Authenticated Internal Requests"]
        HANDLER["Docker Restart Handler<br/>Exact Container Allowlist"]
    end

    subgraph OBS["Observability Stack · Docker Compose"]
        PROM["Prometheus<br/>Scraping · Rules · Alerts"]
        GRAF["Grafana<br/>Provisioned Dashboard"]
    end

    ANS["Ansible<br/>Configuration · Deployment · Verification"]

    SYS --> MON
    SVC --> MON
    LOG --> MON
    MON --> API
    API -->|Metrics endpoint| PROM
    PROM -->|PromQL datasource| GRAF
    API -.->|Failure + explicit policy| POLICY
    POLICY -.->|Only when configured| WORKER
    WORKER -.-> HANDLER
    ANS -.->|Manages deployment| API
    ANS -.-> PROM
    ANS -.-> GRAF

    classDef core fill:#172554,stroke:#60a5fa,color:#fff
    classDef obs fill:#064e3b,stroke:#34d399,color:#fff
    classDef recovery fill:#713f12,stroke:#fbbf24,color:#fff
    class API,MON core
    class PROM,GRAF obs
    class POLICY,WORKER,HANDLER recovery
  

## Prerequisites

- macOS on Apple Silicon or another Docker-compatible host.
- Python 3.9 or newer.
- Docker Desktop, when using the containerized API.
- Git.

## Initial setup

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

The `.env` file contains development-only defaults and must not be committed.

## Run the foundation API

With the virtual environment active:

```bash
uvicorn app.main:app --reload
```

The API is intended for local development only. It has no authentication yet and must not be exposed publicly without suitable access controls.

Available endpoints:

- `GET /health`: process liveness check; does not run monitoring checks.
- `GET /status`: complete coordinator report. Returns `200` for `HEALTHY` or `DEGRADED`, and `503` for `UNHEALTHY`.
- `GET /logs?limit=20`: bounded severity counts and recent error/critical entries. The limit is restricted to 1-100 and the log path comes only from local configuration.
- `GET /metrics`: Prometheus text-format metrics generated from the same coordinator report used by `/status`.
- `GET /docs`: generated local API documentation.

Example requests:

```bash
curl http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/status
curl 'http://127.0.0.1:8000/logs?limit=10'
curl http://127.0.0.1:8000/metrics
```

The API reads service and log locations from `INFRAWATCH_SERVICES_CONFIG`, `INFRAWATCH_LOG_PATH`, `INFRAWATCH_DISK_PATH`, and `INFRAWATCH_CPU_INTERVAL`. Relative paths are resolved from the project root. The shared monitoring components are initialized once when the application is created.

## Run with Docker Compose

Docker Desktop is required on macOS, including Apple Silicon Macs. Docker Compose v2 is included with current Docker Desktop installations. The Compose stack contains the InfraWatch API, Prometheus, and Grafana in this step.

Build and start the API:

```bash
docker compose up --build
```

Run it in the background:

```bash
docker compose up --build -d
```

Inspect service health and container logs:

```bash
docker compose ps
docker compose logs -f api
```

The API health check calls `GET /health`. The API is published only on `127.0.0.1:8000`, so it is not exposed on every host network interface by default. Stop and remove the container with:

```bash
docker compose down
```

Compose sets container-specific paths: `/app/config/services.yaml` is mounted read-only from [`config/services.yaml`](config/services.yaml), and `/app/logs` is mounted from the local `logs/` directory. Local development resolves relative configuration paths from the project root instead. The optional `logs/app.log` file may be absent; `/health` remains available and `/logs` reports a clear read failure.

The container runs as the unprivileged `infrawatch` user, does not use host networking or the Docker socket, and contains no credentials. This API is still intended for local development and should not be exposed publicly without authentication and access controls.

External alert delivery is intentionally not configured yet.

## Prometheus

The Compose stack runs Prometheus beside the API on the private Compose network. Prometheus scrapes the API at `http://api:8000/metrics`; it must use the service DNS name `api`, not `localhost`, from inside the Prometheus container.

- Scrape configuration: [`config/prometheus/prometheus.yml`](config/prometheus/prometheus.yml)
- Recording and alerting rules: [`config/alerts/infra_rules.yml`](config/alerts/infra_rules.yml)
- Persistent data volume: `prometheus_data`
- Local Prometheus UI: `http://127.0.0.1:9090`

Start the API and Prometheus together:

```bash
docker compose up --build -d
```

Open the Prometheus UI, then inspect `Status > Targets` for the `infrawatch-api` target and `Alerts` for loaded rule state. The raw endpoints are also useful during development:

```bash
curl http://127.0.0.1:9090/-/ready
curl http://127.0.0.1:9090/api/v1/targets
curl http://127.0.0.1:9090/api/v1/rules
```

Example PromQL queries based on the metrics emitted by the existing API exporter:

```promql
infrawatch_cpu_utilization_percent
infrawatch_memory_utilization_percent
infrawatch_disk_utilization_percent
infrawatch_service_availability{required="true"}
up{job="infrawatch-api"}
```

Stop the stack when finished:

```bash
docker compose down
```

The YAML configuration and rule expressions are structurally tested locally. Runtime scrape health, rule loading, and Prometheus ingestion require Docker and Prometheus to be available; they are not claimed as verified when those tools are unavailable.

## Grafana

Grafana provides the local dashboard layer over Prometheus. It uses the internal datasource URL `http://prometheus:9090`, persists its state in the named `grafana_data` volume, and is published locally at:

```text
http://127.0.0.1:3000
```

Provisioning files are version-controlled at:

- Datasource: [`config/grafana/provisioning/datasources/prometheus.yml`](config/grafana/provisioning/datasources/prometheus.yml)
- Dashboard provider: [`config/grafana/provisioning/dashboards/infrawatch.yml`](config/grafana/provisioning/dashboards/infrawatch.yml)
- Dashboard JSON: [`config/grafana/dashboards/infrawatch-overview.json`](config/grafana/dashboards/infrawatch-overview.json)

Set local Grafana credentials before starting the stack:

```bash
cp .env.example .env
# Edit GF_SECURITY_ADMIN_USER and GF_SECURITY_ADMIN_PASSWORD in .env
docker compose up --build -d
```

The values in `.env.example` are development-only placeholders. For local setup, copy the file exactly as shown above; Compose passes `GF_SECURITY_ADMIN_USER` and `GF_SECURITY_ADMIN_PASSWORD` to Grafana. Change the password before any nonlocal deployment. `.env` is excluded from version control and credentials are not embedded in the provisioning files.

Open the dashboard after Grafana is ready, or inspect its health endpoint:

```bash
open http://127.0.0.1:3000
curl http://127.0.0.1:3000/api/health
docker compose logs -f grafana
```

If the datasource or dashboard is missing, check `docker compose logs grafana`, confirm that the provisioning mounts exist, and verify Prometheus readiness at `http://127.0.0.1:9090/-/ready`. The dashboard uses the verified InfraWatch metrics including CPU, memory, disk, uptime, service availability and response time, log severity counts, `up`, and Prometheus `ALERTS`. Dashboard JSON and provisioning YAML are structurally validated by pytest; live panels and datasource health remain unverified until the stack is run.

## Ansible automation

Ansible is organized into four roles:

- `prerequisites`: checks source files and Docker/Compose availability without installing packages.
- `configuration`: creates the deployment directory and copies only application, Compose, and monitoring configuration. It never copies `.env`, `.venv`, `.git`, tests, or caches.
- `deployment`: validates Compose and starts services only when explicitly requested.
- `verification`: checks API liveness, API monitoring status, Prometheus readiness, and Grafana readiness with bounded retries.

The default inventory at [`ansible/inventory/local.yml`](ansible/inventory/local.yml) targets only `127.0.0.1` using a local connection with privilege escalation disabled. The safe `site.yml` playbook validates project prerequisites without starting services:

```bash
export ANSIBLE_CONFIG=ansible/ansible.cfg
ansible-playbook --syntax-check -i ansible/inventory/local.yml ansible/playbooks/site.yml
ansible-playbook -i ansible/inventory/local.yml ansible/playbooks/site.yml
```

`ANSIBLE_CONFIG` is explicit because the project configuration is stored under `ansible/` rather than at the repository root. With Ansible Core 2.15, `roles_path = roles` resolves relative to the loaded `ansible/ansible.cfg`, so the existing roles resolve consistently from the repository root without machine-specific absolute paths.

Use check mode for a dry run where supported:

```bash
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook --check -i ansible/inventory/local.yml ansible/playbooks/site.yml
```

Deployment is a separate, explicit operation. It requires Docker, Docker Compose, and a separately managed `.env` in the deployment directory:

```bash
mkdir -p /tmp/infrawatch
cp .env.example /tmp/infrawatch/.env
# Edit /tmp/infrawatch/.env and replace development credentials.
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/local.yml ansible/playbooks/deploy.yml \
	-e infrawatch_deploy_dir=/tmp/infrawatch
```

The deploy playbook uses the explicit Compose project name `infrawatch-ansible-local` and loopback ports `18000` (API), `19090` (Prometheus), and `13000` (Grafana), so it does not collide with the normal stack on `8000`, `9090`, and `3000`. It affects only `/tmp/infrawatch`, the three isolated containers, and project-scoped named volumes for that Compose project. It does not overwrite the repository `.env` or the existing stack's volumes. The isolated deployment can be removed after verification with:

```bash
COMPOSE_PROJECT_NAME=infrawatch-ansible-local docker compose -f /tmp/infrawatch/docker-compose.yml down
```

The source files copied by configuration management are `app/`, `config/`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.env.example`, and `/tmp/infrawatch/logs`. No `.env`, `.venv`, `.git`, tests, caches, or host-wide settings are copied.

Run verification against an already running target without starting services:

```bash
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/local.yml ansible/playbooks/verify.yml
```

For a separate Linux host, create a separate inventory file rather than changing the safe local default. Set an explicit `ansible_host`, `ansible_user`, and connection method, then pass that inventory with `-i`; enable `ansible_become` only when the target's documented permissions require it. Keep SSH keys and credentials outside the repository.

The deployment target, deployment directory, service-start flag, build flag, and verification URLs are variables. `site.yml` has `infrawatch_start_services: false`; only `deploy.yml` enables startup. If Docker is missing, validation reports that deployment was not attempted, while `deploy.yml` fails with a clear prerequisite error. Ansible is not installed in the current development environment, so syntax checks are documented but not locally verified.

## Alert validation and failure recovery

The alert rules in [`config/alerts/infra_rules.yml`](config/alerts/infra_rules.yml) are evaluated every 15 seconds:

- `InfraWatchAPITargetUnavailable`: `up{job="infrawatch-api"} == 0` for 2 minutes; critical.
- `InfraWatchRequiredServiceDown`: required service availability equals zero for 2 minutes; critical. Optional services do not match this rule.
- `InfraWatchHighCPUUtilization`: CPU is strictly greater than 85 percent for 5 minutes; warning.
- `InfraWatchHighMemoryUtilization`: memory is strictly greater than 85 percent for 5 minutes; warning.
- `InfraWatchHighDiskUtilization`: disk is strictly greater than 85 percent for 5 minutes; warning.

Run the safe local failure-and-recovery demonstration without Docker or external services:

```bash
source .venv/bin/activate
python -m scripts.failure_recovery_demo
```

The harness binds an ephemeral loopback port, checks a healthy response, changes only its own response to HTTP 503, verifies `DOWN`, restores HTTP 200, verifies `UP`, and cleans up the server automatically. The same sequence is covered by `tests/test_failure_recovery.py`.

Inspect live alert state when Prometheus is running:

```bash
curl http://127.0.0.1:9090/api/v1/alerts
curl http://127.0.0.1:9090/api/v1/rules
```

The Grafana dashboard's `Active Prometheus Alerts` panel queries the Prometheus-generated `ALERTS{alertstate="firing"}` series. A recovered condition stops matching its alert expression, so Prometheus resolves it after the next evaluation; the `for` delay applies again if the condition returns.

The tests perform three distinct levels of validation: YAML/JSON structural checks, deterministic synthetic evaluation of the known rule shapes including pending/firing/resolved transitions, and the local HTTP failure/recovery sequence. These tests do not claim full PromQL evaluation or live alert ingestion. `promtool` and Docker runtime checks require those tools and a running stack.

## Final integration audit

The repository integration checklist is:

- [x] FastAPI configuration paths match Compose paths under `/app`.
- [x] Prometheus scrapes `api:8000/metrics` and loads the mounted alert rules.
- [x] Grafana uses the internal `http://prometheus:9090` datasource and provisioned dashboard paths.
- [x] Dashboard, alert, and recording-rule expressions reference exported or Prometheus-generated metrics.
- [x] Ansible deployment paths match the Compose project layout and verification URLs match `/health`, `/status`, `/-/ready`, and `/api/health`.
- [x] Required service failures propagate to the health report and serialized service URLs redact credentials and query tokens.
- [x] Loopback-only host bindings, non-root API execution, read-only configuration mounts, and absence of Docker socket access are structurally checked.

Validation status:

- Unit and integration tests: `python -m pytest -q` passes locally.
- Static configuration: YAML and JSON parsing plus structural tests pass locally.
- Runtime verified: the in-process API tests and loopback failure/recovery harness run successfully without external services.
- Runtime not verified: Docker image/Compose startup, Prometheus ingestion and alert evaluation, Grafana datasource/dashboard loading, and Ansible playbook execution require tools unavailable in the current environment.

This project is suitable as a GitHub portfolio demonstration of modular Python monitoring, a FastAPI integration, Prometheus/Grafana configuration, deterministic failure testing, and safe Ansible deployment scaffolding. It remains intentionally local-development focused: authentication, external notification delivery, production secret management, and remote deployment hardening are not implemented.

## Run tests

```bash
python -m pytest
```

## Monitoring engine

The monitoring engine is independent of FastAPI and can be called directly:

- `app/monitoring/system_metrics.py` collects CPU, memory, disk, and uptime metrics with `psutil`. The disk path and CPU sampling interval are configurable.
- `app/monitoring/service_checker.py` checks configured HTTP and HTTPS services with bounded timeouts using Python's standard library. Each service is checked independently.
- `app/log_parser/log_parser.py` reads a bounded window of a configured log file and counts recognized severity levels without executing file contents.
- `app/monitoring/health_monitor.py` combines those results. Required service failures and system collection failures are `UNHEALTHY`; optional service failures, log read failures, and configured warning conditions are `DEGRADED`.

Service definitions live in [`config/services.yaml`](config/services.yaml). The included endpoint is a local example only; it is not assumed to be running. Add services under `services` and configure `required`, `timeout_seconds`, and `expected_status_codes` as needed.

Run a local demonstration without starting the API server:

```bash
source .venv/bin/activate
python -m scripts.run_monitoring_demo \
	--config config/services.yaml \
	--log tests/fixtures/sample_application.log
```

Because the sample service points at `127.0.0.1:8000` and the FastAPI server is intentionally not started in this step, this demonstration normally reports `UNHEALTHY`. That result confirms the engine distinguishes an unavailable required service from a successful check.

The test log at [`tests/fixtures/sample_application.log`](tests/fixtures/sample_application.log) is synthetic test data, not a real system log. The parser reads at most 1,000 lines by default, so large files do not load entirely into memory.

The monitoring engine, local FastAPI routes, Prometheus configuration, Grafana provisioning, and Ansible scaffolding do not configure external alert delivery. That integration is reserved for a later step.

For deployment security, secret handling, recovery isolation, TLS, firewall, backup, and VPS readiness requirements, see [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

## Safe service recovery

Service monitoring and recovery are separate. A failed health check is reported normally; recovery is attempted only when that service has an explicit policy with `enabled: true` and a named action. The default configuration keeps recovery disabled:

```yaml
recovery:
	enabled: false
	action: none
	max_attempts: 1
	cooldown_seconds: 300
	timeout_seconds: 5
```

Recovery actions are not shell commands. The `action` value selects a handler registered by trusted application code; arbitrary executables, command strings, API input, and untrusted configuration cannot create actions. The built-in API monitor uses dry-run recovery, so normal monitoring never restarts a host process or container. A real restart handler must be explicitly injected by a later deployment integration.

Every action is bounded by a timeout, retry limit, and cooldown. Results are included in the coordinator report under `recoveries` and logged with service, action, status, attempt, and message fields. Recovery exceptions are isolated from monitoring collection.

Run the recovery tests without Docker or external services:

```bash
.venv/bin/python -m pytest -q tests/test_recovery.py
```

The suite covers successful and failed handlers, retry limits, cooldowns, disabled recovery, dry-run behavior, and recovery of a disposable loopback-only HTTP service. It does not restart the existing API, Prometheus, or Grafana containers.

### Docker recovery handler

The optional `DockerContainerRestartHandler` uses the Docker Engine API through the Python Docker SDK. It does not invoke a shell or accept command strings. It can restart only an exact container name present in the trusted `INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS` allowlist and only when all of these gates are explicit:

```env
INFRAWATCH_RECOVERY_DRY_RUN=false
INFRAWATCH_DOCKER_RECOVERY_ENABLED=true
INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS=infrawatch-recovery-disposable
```

The API defaults remain `dry_run=true` and Docker recovery disabled. Docker socket access is a high-privilege control-plane capability: anyone able to use it can control the Docker host. The existing API Compose service does not mount `/var/run/docker.sock`, so the handler is not available inside the production API container by default. Use the handler only from a separately trusted local/deployment process, with a dedicated disposable or explicitly authorized target. Do not add a Docker socket mount to the API casually.

Run the Docker handler tests:

```bash
.venv/bin/python -m pytest -q tests/test_docker_recovery.py
```

The runtime test creates one disposable container with an unused loopback port (`18081`), stops it, restarts it through the allowlisted SDK handler, verifies HTTP recovery, and removes it in `finally`. It does not touch the existing Compose project or its volumes.
