# Phase P01 Local Infrastructure Guide

This guide manages only the local PostgreSQL, Redis, and Chroma containers. It does not add
application database clients or any later-phase AI features.

## Before every start

Open Docker Desktop and wait until its engine reports that it is running. From the repository
root, synchronize the local environment once if needed:

```bash
uv sync
```

The repository needs a local `.env`. Create it without overwriting an existing file:

```bash
cp -n .env.example .env
git check-ignore -v .env
```

The second command should show that `.gitignore` excludes `.env`. Never commit `.env`.

## Validate and start

Validate the resolved Compose configuration before starting containers:

```bash
docker compose config --quiet
```

Pull the exact image versions selected for this phase, then start in the background and wait
for services with container healthchecks:

```bash
docker compose pull
docker compose up -d --wait --wait-timeout 120
```

If `docker compose pull` remains on `Pulling`, test Docker Hub connectivity with:

```bash
curl --head --max-time 10 https://registry-1.docker.io/v2/
```

An HTTP response such as `401 Unauthorized` proves that the Registry is reachable; the
authentication challenge is expected for this probe. A timeout indicates a host network or
proxy problem. Open Docker Desktop Settings, go to **Resources → Proxies**, and select the
system proxy or enter the proxy that is correct for your network. Do not copy an unknown proxy
address from the internet. Restart the pull after Docker Desktop applies the setting.

Chroma is checked from the host instead of assuming that its container includes `curl` or
another HTTP command. Run all three independent checks with:

```bash
uv run python scripts/check_infra.py
```

Expected lines begin with `PASS PostgreSQL`, `PASS Redis`, and `PASS Chroma`. Any failure makes
the script exit with a nonzero status.

## Status and logs

Show current container state:

```bash
docker compose ps
```

Follow all logs, or only one service's logs:

```bash
docker compose logs --follow
docker compose logs --follow postgres
docker compose logs --follow redis
docker compose logs --follow chroma
```

Press Control-C to stop following logs. This does not stop the containers.

List this Compose project's named volumes:

```bash
docker compose volumes
```

## Stop or remove while retaining data

Stop containers but keep them and all data:

```bash
docker compose stop
```

Start those existing containers again:

```bash
docker compose start --wait --wait-timeout 120
```

Remove containers and the project network while retaining named volumes:

```bash
docker compose down
```

A later `docker compose up -d --wait` recreates containers and reuses those volumes.

## Danger: permanently delete all local infrastructure data

The following command deletes the containers **and all three named volumes**. PostgreSQL,
Redis, and Chroma local data cannot be recovered unless you made a backup. Do not run it as a
normal stop command.

```bash
docker compose down --volumes
```

## Port conflicts

The default host ports are PostgreSQL `5432`, Redis `6379`, and Chroma `8001`. Check which
process is already listening before starting Docker:

```bash
lsof -nP -iTCP:5432 -sTCP:LISTEN
lsof -nP -iTCP:6379 -sTCP:LISTEN
lsof -nP -iTCP:8001 -sTCP:LISTEN
```

No output means the port is free. Output containing a process means that port is occupied.
Either stop that process or change the matching value in `.env`:

```text
POSTGRES_PORT=5432
REDIS_PORT=6379
CHROMA_PORT=8001
```

After changing a port, run `docker compose config --quiet` and `docker compose up -d --wait`
again. If Redis's host port changes, also update the port inside `REDIS_URL`.

## PostgreSQL initialization variables

`POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` initialize PostgreSQL only when its data
directory is empty. Once `postgres_data` contains a database, changing these values in `.env`
does not rename the existing user, change its password, or create a different database.

For an existing database, make changes with PostgreSQL administration commands in a later,
intentional task. For a disposable local database, the dangerous `docker compose down
--volumes` reset applies new initialization values on the next start, but permanently deletes
all current local data.
