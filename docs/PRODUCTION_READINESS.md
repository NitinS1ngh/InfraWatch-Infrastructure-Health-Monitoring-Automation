# InfraWatch Production Readiness

This document separates controls implemented and tested locally from work required before a public Linux deployment. InfraWatch is currently a local-development and private-network system.

## Architecture

- **API**: FastAPI application exposing `/health`, `/status`, `/logs`, and `/metrics`.
- **Monitoring engine**: `psutil` system metrics, HTTP service checks, and bounded application-log parsing.
- **Prometheus**: Scrapes `api:8000/metrics`, evaluates recording and alert rules.
- **Grafana**: Uses the internal Prometheus datasource and provisioned dashboard.
- **Recovery worker**: Opt-in Compose profile. It is not part of the normal stack and is the only component that can receive Docker socket access.
- **Ansible**: Local-safe validation, isolated deployment, and bounded post-deployment verification.

## Safe local development

```bash
cp .env.example .env
# Keep the development Grafana values local and change them before nonlocal use.
docker compose up --build -d
.venv/bin/python -m pytest -q
```

Default local bindings are loopback-only: API `8000`, Prometheus `9090`, and Grafana `3000`. Recovery is disabled and dry-run by default. The optional application log may be absent; `/status` reports the missing source while service health remains meaningful.

## Production environment variables

Set these through a secret manager or protected deployment environment, never in Git:

- `GF_SECURITY_ADMIN_USER`: Grafana administrator username.
- `GF_SECURITY_ADMIN_PASSWORD`: strong Grafana administrator password.
- `INFRAWATCH_SERVICES_CONFIG`: container path to service configuration.
- `INFRAWATCH_LOG_PATH`: container path to the application log.
- `INFRAWATCH_BIND_ADDRESS`, `INFRAWATCH_API_PORT`, `INFRAWATCH_PROMETHEUS_PORT`, `INFRAWATCH_GRAFANA_PORT`: bind and port policy.
- `INFRAWATCH_RECOVERY_DRY_RUN`: keep `true` until recovery has been explicitly approved.
- `INFRAWATCH_DOCKER_RECOVERY_ENABLED`: keep `false` for the standard deployment.
- `INFRAWATCH_RECOVERY_ALLOWED_CONTAINERS`: exact disposable container names only.
- `INFRAWATCH_RECOVERY_WORKER_URL`: private internal worker URL.
- `INFRAWATCH_RECOVERY_WORKER_TOKEN`: random secret of at least 16 characters; never use the example placeholder.

The standard Ansible deployment rejects placeholder secrets and refuses to start when recovery is enabled. Recovery requires a separate reviewed deployment procedure.

## Linux deployment prerequisites

- Supported Linux host with Docker Engine and Compose v2.
- Ansible Core 2.15+ in the dedicated `.venv-ansible` environment.
- A protected `.env` created outside the repository.
- A reverse proxy terminating TLS and enforcing authentication before API, Prometheus, or Grafana access.
- Firewall rules allowing only the reverse proxy and required administration paths.
- No public binding of the recovery worker or Docker socket.

Run syntax checks with `ANSIBLE_CONFIG=ansible/ansible.cfg`, then use `site.yml` for validation and `deploy.yml` only against an explicitly selected isolated target. Do not use the localhost inventory as a production inventory.

## Recovery security

The API never mounts `/var/run/docker.sock`. The recovery worker accepts only authenticated `POST /recover` requests with the fixed `docker_restart` action and an exact allowlisted container name. It has no host port. Recovery retries, cooldowns, timeouts, and concurrent-request protection are enforced in code.

A Docker socket is effectively host-level Docker control. The current worker socket mount is suitable only for a private, opt-in development profile and was tested with disposable containers. Before production use, replace it with a narrowly scoped Docker socket proxy that permits only the required container inspect/restart operations, or isolate the worker on a dedicated control host. This proxy is not implemented or claimed as verified here.

Rollback for a recovery rollout:

1. Set `INFRAWATCH_RECOVERY_DRY_RUN=true`.
2. Set `INFRAWATCH_DOCKER_RECOVERY_ENABLED=false`.
3. Stop only the recovery profile worker.
4. Keep the existing monitoring stack running.
5. Review recovery audit logs and Prometheus alerts.

## Operations

- Persist Prometheus and Grafana volumes and back them up before upgrades.
- Configure log rotation and retention for API, worker, Prometheus, and Grafana logs.
- Pin image versions and preferably immutable image digests.
- Scan Python dependencies and container images before deployment.
- Rotate Grafana and worker credentials; do not print them in logs.
- Test alert transitions and recovery against disposable services before production changes.
- Record incidents, recovery requests, operator approvals, and rollback actions.

## Readiness checklist

### Implemented and locally tested

- Loopback-only default ports.
- Non-root API image.
- API without Docker socket access.
- Opt-in recovery worker with exact allowlist, token authentication, dry-run, retries, cooldowns, timeouts, and concurrency protection.
- Disposable-container recovery test through the worker.
- Prometheus/Grafana provisioning and Ansible syntax checks.
- Placeholder-secret rejection in the Ansible deployment role.

### Required before public production deployment

- TLS reverse proxy and API/Grafana authentication.
- Firewall and private-network policy review.
- Docker socket proxy or dedicated recovery host.
- Production secret manager and credential rotation.
- Image digest pinning and vulnerability scanning.
- Backup/restore test for Prometheus and Grafana data.
- Log retention, centralized audit logs, and incident response procedures.
- Linux host validation and a reviewed production inventory.

No public deployment, GitHub push, or production firewall change has been performed.
