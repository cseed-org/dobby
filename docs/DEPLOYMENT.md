# Docker deployment: Raspberry Pi and Windows

Dobby runs on Windows Docker Desktop (`linux/amd64`) and 64-bit Raspberry Pi OS (`linux/arm64`). Use [README.md](../README.md#set-up-dobby) for the Discord, Gemini, Composio and dashboard-login setup; this page covers the machine itself. No paid cloud server is needed.

## Prepare the Pi

Install 64-bit Raspberry Pi OS and Docker Engine with Compose using [Docker's Debian instructions](https://docs.docker.com/engine/install/debian/). A Pi 4/5 with 4 GB RAM is recommended: Postgres, the API and the Next.js frontend run beside the bot. Confirm:

```bash
uname -m                      # aarch64
docker compose version
sudo systemctl enable --now docker
```

Docker group membership is effectively root access; give it only to a trusted user or run through `sudo`.

For the optional update timer, keep the checkout at `/opt/dobby`:

```bash
sudo mkdir -p /opt/dobby
sudo chown "$(id -u):$(id -g)" /opt/dobby
git clone https://github.com/YOUR_OWNER/YOUR_REPO.git /opt/dobby
cd /opt/dobby
cp .env.example .env
chmod 600 .env
id -u; id -g
```

Set `DOBBY_UID`/`DOBBY_GID` in `.env` to those IDs, then fill in the rest per the README.

## Move from Windows to the Pi

Only `.env` needs to move — the service connections live in Composio, not in local files. Transfer it over SSH/SCP, never Git:

```powershell
scp .env piuser@raspberrypi.local:/opt/dobby/.env
```

On the Pi, edit the transferred `.env`: set the Pi UID/GID, and change `DASHBOARD_URL` / `API_URL` to how browsers will reach the Pi (for example `http://raspberrypi.local:3000` and `http://raspberrypi.local:8000`). Add those hosts to the OAuth redirect URIs in Google Cloud and the Discord application. Then:

```bash
cd /opt/dobby
docker compose up -d --build
docker compose logs --tail 50 -f bot dashboard
```

**Stop Windows Dobby first** (`docker compose down`): one bot instance per Discord token. The Postgres data does not move automatically; either re-add users on the Pi's dashboard or restore a `pg_dump` from Windows (`docker compose exec -T postgres psql -U dobby dobby < backup.sql` after the first start).

## Test locally in Docker

Before deploying, confirm the image is sound. These run with networking disabled and need no credentials:

```text
docker compose -f compose.test.yaml run --rm tests
docker compose -f compose.test.yaml run --rm lint
```

`compose.test.yaml` builds the Dockerfile's `test` stage on the same base layers the runtime uses. The deployed `runtime` stage is last in the Dockerfile, so a plain `docker build .` selects an image with no tests.

Once `.env` exists, validate the bot's settings without contacting Discord:

```text
docker compose run --rm --no-deps bot python -m bot.main --check
```

Exit `0` prints `config_ok`; exit `2` names the setting to fix. `docker compose config --quiet` additionally checks that the dashboard's required variables are set. Do both before the first `up` on a new machine, because `restart: unless-stopped` otherwise retries a misconfigured container indefinitely.

If `.env` is missing when you run `docker compose`, Docker may create a **directory** named `.env`; delete it and recreate the file (`python scripts/bootstrap.py` does this).

## Run on either machine

```text
docker compose up -d --build
docker compose ps
docker compose logs --tail 50 -f bot
```

`migrate` runs Alembic and exits; `bot`, `dashboard` and `frontend` then start. The bot exposes no ports, runs non-root with all capabilities dropped, a read-only filesystem, rotated logs and a 512 MB memory cap. The dashboard publishes 8000 and the frontend 3000 on the host; put them behind a LAN firewall or reverse proxy if the Pi is reachable from elsewhere. Windows Docker Desktop must remain running; on the Pi, Docker starts at boot.

`docker compose down` removes containers, not the `pgdata` volume or `.env`. After changing `.env`, recreate with `docker compose up -d --force-recreate --no-build`; if `API_URL` changed, also `docker compose build frontend`.

## Publish images from GitHub

`.github/workflows/publish.yml` runs on main pushes. It tests the source, validates Compose, then builds and publishes AMD64 and ARM64 **bot** images to:

- `ghcr.io/owner/repository:main`
- `ghcr.io/owner/repository:sha-COMMIT_SHA`

The workflow uses GitHub's built-in `GITHUB_TOKEN`; no cloud key or application secret is required. After the first publish, change the package's visibility to **Public** so the Pi can pull without credentials. Protect `main` and workflow changes: a trusted image can read runtime credentials. The dashboard and frontend are built locally from the checkout.

## Pull a published image on Windows or Pi

Set this in `.env`, using lowercase owner/repository names:

```dotenv
DOBBY_IMAGE=ghcr.io/your_owner/your_repo:main
```

Then run:

```text
docker compose -f compose.yaml -f compose.registry.yaml pull bot
docker compose -f compose.yaml -f compose.registry.yaml up -d --no-build --pull never bot
```

The override only replaces the `bot` service's image; the other services are unchanged. Use both files for starts/recreates in registry mode so you do not switch back to local builds.

## Automatic updates on the Pi

First verify the published-image commands work. Keep the checkout at `/opt/dobby` with `DOBBY_IMAGE` set, then install the timer:

```bash
cd /opt/dobby
sudo install -m 644 deploy/dobby-update.service /etc/systemd/system/dobby-update.service
sudo install -m 644 deploy/dobby-update.timer /etc/systemd/system/dobby-update.timer
sudo systemctl daemon-reload
sudo systemctl enable --now dobby-update.timer
sudo systemctl start dobby-update.service
systemctl list-timers dobby-update.timer
sudo journalctl -u dobby-update.service -n 30 --no-pager
```

Every five minutes plus a small randomized delay, the timer runs `scripts/update-pi.sh` as root: it pulls first (a failed pull leaves the current container running), then recreates the `bot` service if its image changed. `flock` prevents overlapping runs. No automatic Git pull occurs, so Compose files, migrations, the dashboard and the frontend change only through a deliberate `git pull` and rebuild.

Updates briefly reconnect Discord and discard any pending Confirm previews. Only trusted administrators should be able to modify `/opt/dobby`, since the root timer reads its Compose files. Old images are not pruned automatically; check `docker system df` occasionally.

To stop updates:

```bash
sudo systemctl disable --now dobby-update.timer
sudo systemctl stop dobby-update.service
```

Disable the timer **before** stopping Dobby for maintenance; otherwise the next check starts it again.

## Rollback and configuration updates

Disable the timer, set `DOBBY_IMAGE` to a known-good `:sha-COMMIT_SHA` tag, then run the published-image pull/up commands. This rolls back bot code, not anything already published to a calendar or social account.

For Compose, migration, dashboard or frontend changes, run `git pull --ff-only`, then `docker compose up -d --build` (which re-runs `migrate`). Reinstall changed systemd units and `sudo systemctl daemon-reload`. Never copy `.env.example` over your existing `.env`.

## Live smoke test

1. Without an allowed role/user grant, try `/events` and a mention; nothing should happen beyond a refusal.
2. As an allowed user, `/help` lists Google Calendar, Notion, Instagram and LinkedIn.
3. `/events` returns the connected calendar's events; `@Dobby schedule a test sync tomorrow at 10am and invite <a registered teammate>` creates it with that person's calendar email.
4. `/notion search query:<a known page>` finds it.
5. `/linkedin post text:test` shows a preview; have someone else click Confirm (refused), then Cancel it yourself. Confirm one real post only when you mean it.
6. `/instagram posts` lists our posts; `/instagram story post:1` previews the story; Cancel.
7. On the dashboard, the audit log shows the tool calls above as `ok`, with no arguments or results stored.
8. Restart the bot; `bot_ready` appears and an old preview's buttons no longer work.
9. If updates are enabled, push a harmless change and verify publication plus the Pi update.
