# Deploying Lanka Link v3

One host runs the whole stack. The images are built by GitHub Actions and pulled from GHCR, the
database is Neon, and Caddy on the host gets the certificate. Nothing is ever built on the server.

```
push to main
   |
   +-- ci.yml        tests, types, compose validation
   +-- release.yml   builds 16 images, pushes them to ghcr.io
          |
          +-- deploy.yml   runs the Ansible playbook against the host
                 |
                 +-- git pull, write .env, docker compose pull, up -d --wait, smoke test
```

## 1. The host

`infra/deploy/terraform` creates it: one Ubuntu 24.04 EC2 instance in **ap-southeast-1
(Singapore)**, a security group open on 22, 80 and 443, and an elastic IP. Singapore because the
Neon project belongs there too, and every page in this product waits on at least one database
round trip.

```bash
cd infra/deploy/terraform
terraform init
terraform apply -var="key_name=your-ec2-keypair" -var='ssh_cidrs=["YOUR.IP.ADDR.ESS/32"]'
terraform output public_ip
```

Default size is `t3.xlarge` (4 vCPU, 16 GB) with an 80 GB disk. Both are about the models: NLLB and
Whisper stay resident, and their image layers are large. A smaller instance will start and then
fail health checks.

Point the site's A record at the elastic IP before the first deploy, because Caddy asks Let's
Encrypt for a certificate on first start.

**Azure instead.** Nothing above is AWS-specific except the Terraform. An Ubuntu VM in
`southeastasia` with the same ports open, the same size, and its address in the inventory works
without any other change: the playbook installs Docker itself and the compose stack is the same.

## 2. Secrets

Set these as repository secrets (Settings, Secrets and variables, Actions). The deploy job is the
only thing that reads them, and it fails early if `DEPLOY_HOST` is missing, so a fork can never
deploy.

| Secret | What it is |
| --- | --- |
| `DEPLOY_HOST` | The elastic IP or host name |
| `DEPLOY_USER` | The SSH user; it needs passwordless sudo |
| `DEPLOY_SSH_KEY` | A private key made for deploys only; its public half goes in the server's `~/.ssh/authorized_keys` |
| `SITE_DOMAIN` | The name the certificate is issued for. With no domain of your own, `<ip-with-dashes>.sslip.io` resolves to the server and gets a real certificate |
| `ACME_EMAIL` | Where Let's Encrypt sends expiry warnings |
| `NEON_KEY` | The pooled Neon connection string |
| `BETTER_AUTH_SECRET` | `openssl rand -base64 32` |
| `TIMESCALE_PASSWORD`, `MINIO_ROOT_PASSWORD` | Local infrastructure passwords |
| `OLLAMA_API_KEY`, `GOOGLE_API_KEY` | The drafting model and its fallback |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Optional, for sign in with Google |
| `SEED_STAFF_PASSWORD`, `SEED_CUSTOMER_PASSWORD` | Optional; the seeded logins |
| `CI_NEON_KEY` | Not a deploy secret: a Neon **branch** for CI's end to end job. Never the production database, because that job suspends accounts and load tests |

The playbook writes them into `/opt/lanka-link/.env` with mode 0600 on every run, so the server
never holds a secret that the repository's secret store does not. The template is a whitelist of
what the stack reads: the deploy settings (`DEPLOY_*`) and anything else on the deploying machine
never reach the server.

## 3. The deploy

Automatic on every push to main, once `release.yml` has pushed the images. It can also be run by
hand from the Actions tab, or from a laptop:

```bash
cd infra/deploy/ansible
cp inventory.example.ini inventory.ini    # then fill in the host and user
set -a; . ../../../.env; set +a           # the stack's secrets, as environment variables
ansible-playbook -i inventory.ini deploy.yml --private-key ~/.ssh/deploy   -e github_owner=DSEP-G22 -e site_domain=<your-domain> -e v3_tag=sha-<first-7-of-commit>
```

What it does, in order: installs Docker and the compose plugin, checks the repository out at
`/opt/lanka-link` (compose mounts the Caddyfile, the NATS config and the DAGs from it), writes
`.env`, pulls the images (public on GHCR, so no login), runs `up -d --wait` so every health check has to pass,
waits for `https://<domain>/healthz`, then prunes images older than a week.

Deploys are serialised by a concurrency group, so two pushes cannot roll over each other.

Images are pinned to the commit: `V3_TAG=sha-<commit>`. To roll back, run the workflow by hand
against an older commit, or on the host:

```bash
cd /opt/lanka-link
sed -i 's/^V3_TAG=.*/V3_TAG=sha-<older-commit>/' .env
docker compose -f compose.yaml -f compose.prod.yaml up -d --wait
```

## 4. What runs where

`compose.prod.yaml` is the production overlay: the edge publishes 80 and 443 instead of 8080 and
uses `infra/caddy/Caddyfile.prod` (automatic HTTPS for `SITE_DOMAIN`), and the Timescale and MinIO
ports are unpublished so they stay inside the compose network. Everything else is the same file
that runs on a laptop.

The optional MLOps profile (MLflow on 5000, Airflow on 8081) is not started by the deploy. Bring
it up by hand when a retrain is due, and do not publish those ports to the internet:

```bash
docker compose --profile mlops up -d mlflow airflow
```

## 5. The database

Neon, not a container. The application holds a single pooled connection class with statement
caching, so one query is one round trip, which makes the project's **region the single biggest
performance decision**. Moving an existing project:

```bash
OLD_DSN='postgresql://...us-east-2...' NEW_DSN='postgresql://...ap-southeast-1...' \
  bash scripts/neon-move.sh
```

Neon cannot change a project's region, so the script copies the data into a project you create in
the new region, leaving the old one untouched until you delete it. Afterwards put the new string
in `.env` (or the `NEON_KEY` secret), recreate the stack, and check the result with
`uv run python scripts/neon-latency.py`.

## 6. After a deploy

```bash
BASE=https://<domain> bash scripts/smoke.sh          # the edge answers
LANKA_URL=https://<domain> uv run --with httpx python -m pytest tests/system -q
LANKA_URL=https://<domain> npx playwright test       # from web/
```

The system suite is safe against a live deployment in the sense that it only appends data, but it
does open real tickets as the seeded personas, so run it against production once, deliberately,
and not on a schedule.

## 7. When something is wrong

| Symptom | Where to look |
| --- | --- |
| The site does not answer at all | `docker compose ps`; the edge is the only service that publishes a port |
| No certificate | `docker compose logs edge`; the A record has to exist before Caddy's first start |
| Sign-in hangs | `docker compose restart auth`; a network drop can leave dead pooled sockets |
| Replies are never drafted | `/admin/models`, verify the `llm_draft` binding; the fallback binding and the circuit breaker are on the same page |
| Everything is slow | `uv run python scripts/neon-latency.py`; if it is not the database, `docker stats` |
