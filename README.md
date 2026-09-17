# Dobby — Discord assistant for a student group

Dobby is a Discord bot plus a small web dashboard. Mention `@Dobby` or use a slash command and it schedules Google Calendar meetings, searches and writes Notion, and drafts Instagram and LinkedIn posts for the group's accounts — always showing a preview and waiting for your **Confirm** before anything is published. Gemini does the understanding; [Composio](https://composio.dev) holds the connections to the outside services; Postgres remembers who is on the team and where to invite them. Everything runs on your own machine in Docker.

## Contents

- [What Dobby does](#what-dobby-does)
- [How it fits together](#how-it-fits-together)
- [Set up Dobby](#set-up-dobby)
- [How to use Dobby](#how-to-use-dobby)
- [Everyday Docker commands](#everyday-docker-commands)
- [Test it in Docker](#test-it-in-docker)
- [Automatic updates from GitHub](#automatic-updates-from-github)
- [Secrets and access](#secrets-and-access)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## What Dobby does

- **Google Calendar:** create, move, rename and delete meetings on the team calendar by talking to it. Invite people by name or `@mention`; each registered user's calendar email comes from the dashboard, so invitees never link anything.
- **Notion:** search the workspace and create pages.
- **Instagram and LinkedIn:** post to the group's accounts, or put one of our Instagram posts on our story. Every publish shows a preview with Confirm/Cancel that only the requester can press.
- **Context, not memory:** every request reads the last 50 human messages in the channel (`CONTEXT_MESSAGE_LIMIT`), live from Discord, so "make this a meeting" works. Nothing conversational is stored — not the messages, not tool arguments, not results. The audit log keeps only *who ran which tool, when, and whether it worked*.
- **One set of service accounts:** Dobby acts through connections an admin makes once on the dashboard (one Composio entity, `COMPOSIO_ENTITY_ID`). Nobody connects personal accounts.
- Server, role/user and channel allowlists; a 10-second per-user cooldown; Docker restart policy, bounded logs, optional automatic Pi updates.

Design: [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/BOT_ARCHITECTURE.md](docs/BOT_ARCHITECTURE.md). Pi deployment: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## How it fits together

`docker compose up` starts five services:

| Service | What it is | Port |
| --- | --- | --- |
| `postgres` | Postgres 16: users and calendar emails, dashboard sessions, which services are connected, the audit log | — |
| `migrate` | Runs the Alembic migrations once, then exits | — |
| `bot` | The Discord bot (Python). Talks to Discord, Gemini, Composio and Postgres. No inbound ports | — |
| `dashboard` | FastAPI API: OAuth or local username/password login, user roster, service-account connections, audit log | 8000 |
| `frontend` | Next.js web UI for the dashboard | 3000 |

Composio sits between Dobby and Google Calendar / Notion / Instagram / LinkedIn: it hosts the OAuth flows, stores the tokens, and exposes each service as "actions" the bot calls. Dobby never sees a Google or Meta token.

## Set up Dobby

Seven steps. Steps 1–5 gather credentials into `.env`, step 6 checks them, step 7 starts everything and connects the services. Run **every** command from the folder you cloned into.

| Step | What it does | Needs a browser? |
| --- | --- | --- |
| 1 | Install Docker, get the code, create `.env` | No |
| 2 | Create the Discord bot, fill in IDs | Yes |
| 3 | Get a Gemini API key | Yes |
| 4 | Get a Composio API key and prepare each service | Yes |
| 5 | Choose dashboard login: OAuth, local LAN account, or both | Yes |
| 6 | Check the configuration | No |
| 7 | Start Dobby, add users, connect the services | Yes |

### Step 1: Install Docker and get the code

| Machine | Requirements |
| --- | --- |
| Windows | Docker Desktop using **Linux containers**, normally with its WSL 2 backend. Start Docker Desktop before running commands. |
| Raspberry Pi | Pi 4/5 with 4 GB RAM recommended (Postgres and Next.js run alongside the bot), **64-bit Raspberry Pi OS**, Docker Engine and the Compose plugin. |

Follow the official [Windows Docker Desktop installation](https://docs.docker.com/desktop/setup/install/windows-install/) or [Docker Engine Debian installation for 64-bit Pi OS](https://docs.docker.com/engine/install/debian/). See the [Pi guide](docs/DEPLOYMENT.md) for permissions and startup.

Clone the repository, open a terminal in its folder and create your configuration file:

```powershell
Copy-Item .env.example .env      # Windows PowerShell
```

```bash
cp .env.example .env && chmod 600 .env   # Pi/Linux
id -u; id -g                              # note these for DOBBY_UID / DOBBY_GID
```

If you have host Python, `python scripts/bootstrap.py` does the same and repairs a `.env` that Docker turned into a directory. On Pi/Linux set `DOBBY_UID` and `DOBBY_GID` in `.env` to the two IDs printed above. Set `POSTGRES_PASSWORD` to something random now.

### Step 2: Create and invite Dobby in Discord

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application named **Dobby**.
2. Under **Bot**, copy the token into `.env` as `DISCORD_TOKEN`, and enable **Message Content Intent** (required for mentions and channel context). No Presence or Server Members intent is needed.
3. **Only if enabling Discord dashboard login:** under **OAuth2**, note the **Client ID** and generate a **Client Secret**; put them in `.env` as `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` (the dashboard's "Sign in with Discord" uses them). Add the redirect URL `http://localhost:8000/auth/discord/callback` (replace the host if the API will be reached elsewhere).
4. Invite the bot with the `bot` and `applications.commands` scopes and these channel permissions: **View Channels**, **Send Messages**, **Send Messages in Threads**, **Read Message History** (without it Dobby answers with no context). Do not grant Administrator or Manage Roles.
5. Enable Discord Developer Mode, copy the server, role and channel IDs into `.env`:

```dotenv
DISCORD_GUILD_ID=YOUR_SERVER_ID
ALLOWED_ROLE_IDS=YOUR_TEAM_ROLE_ID
ALLOWED_USER_IDS=
ALLOWED_CHANNEL_IDS=
MENTION_CHANNEL_IDS=
TEAM_TIMEZONE=America/Los_Angeles
CONTEXT_MESSAGE_LIMIT=50
```

Lists accept comma-separated numeric IDs. At least one user or role must be allowed; there is no administrator bypass. Empty `ALLOWED_CHANNEL_IDS` / `MENTION_CHANNEL_IDS` permit any channel the bot can see; threads use their own IDs. Tell members that mentions send recent channel text and author display names to Gemini.

### Step 3: Get a Gemini API key

Create a key in [Google AI Studio](https://aistudio.google.com/apikey) and set `GEMINI_API_KEY`. The default model is `gemini-2.5-flash-lite` (`GEMINI_MODEL` overrides it). Free-tier content may improve Google's products, so avoid confidential material on that tier. [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).

### Step 4: Composio — the key and the services behind it

Composio is where the service connections live. You create the API key now; the actual accounts are connected from Dobby's dashboard in step 7.

1. Sign up at [composio.dev](https://composio.dev), open **Settings → API keys**, create a key and set `COMPOSIO_API_KEY` in `.env`. Leave `COMPOSIO_ENTITY_ID=dobby` unless you run several Dobbys on one Composio account; the bot and dashboard must use the same value.
2. In Composio's dashboard, open each app Dobby uses and make sure it has an **auth configuration** (Composio calls these integrations). For each app you either use Composio's managed OAuth app, where one is offered, or paste the client ID/secret of your own:

| App | What to prepare | Extra `.env` |
| --- | --- | --- |
| **Google Calendar** | Managed app works. For your own: a Google Cloud OAuth client with the Calendar API enabled and the `calendar.events` scope. Use a dedicated Google account that owns the team calendar; Dobby writes to that account's calendar. | — |
| **Notion** | Managed app works. After connecting, share the pages/databases Dobby may see with the integration inside Notion. | `NOTION_PARENT_PAGE_ID` (optional: where `/notion note` creates pages; copy the 32-hex ID from the page URL) |
| **Instagram** | Needs your own Meta app: a Facebook Page linked to an Instagram **Business or Creator** account, the Instagram Graph API product, and the `instagram_basic` + `instagram_content_publish` permissions. Paste the app ID/secret into Composio's Instagram auth config. | `INSTAGRAM_USER_ID` — the IG user ID (from the Graph API Explorer or Meta Business settings). Required for anything Instagram |
| **LinkedIn** | Needs your own LinkedIn app with the **Share on LinkedIn** product, giving the `w_member_social` scope (plus `openid profile` for the author lookup). Paste its client ID/secret into Composio's LinkedIn auth config. | — |

Composio's own callback URL (shown in each auth config) goes into the Google / Meta / LinkedIn app as the authorized redirect URI — not Dobby's URL.

The bot calls a curated list of Composio actions per service (see `bot/integrations/*/__init__.py`). Composio occasionally renames actions; at startup the bot logs `composio_action_unknown action=…` for any it cannot find and keeps running without it. `docs/BOT_ARCHITECTURE.md` shows how to list the current names.

### Step 5: Dashboard login

Choose `AUTH_MODE=oauth` (default), `local` (username/password on your LAN), or `both` (both options on the sign-in page). Local accounts do not require Google/Discord OAuth credentials or `BOOTSTRAP_ADMIN_EMAIL`. Bot and integration credentials are separate and still required by the full Compose stack.

| `AUTH_MODE` | Sign-in options | Admin setup |
|---|---|---|
| `oauth` (default) | Google or Discord | Bootstrap email or existing admin |
| `local` | Username/password on your LAN | Interactive local-admin command |
| `both` | OAuth and local username/password | Either setup; optionally link accounts |

#### Local username/password setup (another machine on your network)

1. Find the server's LAN IPv4 address (`ipconfig` on Windows or `hostname -I` on Linux). In `.env`, replace the sample IP below with that address:

   ```dotenv
   AUTH_MODE=local
   DASHBOARD_URL=http://192.168.1.50:3000
   API_URL=http://192.168.1.50:8000
   ```

   Keep `SECRET_KEY` set to a random secret. Use this same LAN address from both computers; `localhost` on the second computer would point to the wrong machine.

2. Build the updated migration image and dashboard, apply the database migration, and start the UI:

   ```sh
   docker compose build migrate dashboard frontend
   docker compose run --rm migrate
   docker compose up -d dashboard frontend
   ```

3. Create your admin account (replace `leona` with your chosen username):

   ```sh
   docker compose exec dashboard python -m dashboard.local_admin leona
   ```

   Enter a password of 12-256 characters twice at the hidden prompts. Re-running this command resets the password and revokes that user's existing sessions. To attach local credentials to an existing Google account, append `--email you@gmail.com`; otherwise this creates a separate local admin.

4. On either computer, open `http://192.168.1.50:3000/login` and enter your username/password. If blocked by the host firewall, allow inbound TCP ports 3000 and 8000 from your local subnet on the private network profile.

Set `AUTH_MODE=both` and recreate the dashboard with `docker compose up -d --force-recreate dashboard` to retain local login while enabling OAuth; configure the OAuth credentials and redirect URIs as described below. `AUTH_MODE=oauth` disables local login and existing local sessions. Switching to `local` disables OAuth and existing OAuth sessions.

Local login and local sessions require a loopback or private-network source address. The API blocks all non-local requests in `local` mode. Keep this deployment on a trusted LAN, with no router port forwarding or public tunnel/reverse proxy: Docker/proxies can mask the original client address, so the host firewall remains the network boundary. HTTP is supported for LAN use, but it does not encrypt passwords or session cookies; use HTTPS if other network users are not trusted. The login limiter allows five attempts per source IP per minute in the shipped single-worker process; it resets on restart.

#### OAuth setup


With OAuth enabled, people sign in with a Google account from any email domain or with Discord, and only if an admin has added them first.

1. **Google:** in Google Cloud, create an OAuth client of type **Web application** with authorized redirect URI `http://localhost:8000/auth/google/callback`; set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. Set the Google Auth Platform audience to **External** to allow personal Google accounts. The API requires a verified email and a pre-registered user.
2. **Discord:** done in step 2 (`DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`).
3. Generate a cookie-signing secret and set `SECRET_KEY`:

```powershell
-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })   # PowerShell
```

```bash
openssl rand -hex 32                                                         # Pi/Linux
```

4. Set `BOOTSTRAP_ADMIN_EMAIL` to the exact email address of the Google account you will sign in with (for example, `you@gmail.com`). When OAuth is enabled and no admin exists, startup creates that admin user (or promotes the matching user). If a local admin already exists, use the admin setup/recovery instructions below.
5. `DASHBOARD_URL` is where browsers reach the web UI (default `http://localhost:3000`); `API_URL` is where browsers reach the API (default `http://localhost:8000`). Change both if Dobby runs on a Pi you open from other machines, and use the same hosts in the OAuth redirect URIs above. `API_URL` is baked into the frontend at build time, so rebuild the `frontend` service after changing it.

#### Make yourself an OAuth admin

In the root `.env`, set `BOOTSTRAP_ADMIN_EMAIL=you@gmail.com`, using the exact Google email you will sign in with. Rebuild and recreate the dashboard and frontend:

```text
docker compose up -d --build dashboard frontend
```

Open `http://localhost:3000/login` (or your configured `DASHBOARD_URL`) and choose **Sign in with Google**. When no admin exists, startup creates your admin account or promotes your existing user. No UW address is needed. In Google Cloud, ensure your OAuth app's audience is **External**; an Internal app still blocks accounts outside its organization.

If an admin already exists, the bootstrap setting intentionally does nothing. Have that admin add/promote you under **Users**, or, if you control the deployment and need to recover access, open the database shell:

```text
docker compose exec postgres psql -U dobby -d dobby
```

Run this SQL, replacing the sample email with your Google account email:

```sql
INSERT INTO users (uw_email, display_name, role)
VALUES ('you@gmail.com', 'Your Name', 'admin')
ON CONFLICT (uw_email) DO UPDATE SET role = 'admin';
```

Exit with `\q` and sign in. The legacy database/API field name `uw_email` now stores Google emails from any domain; removing the domain restriction needs no schema migration, but local login requires migration 003.

### Step 6: Check your configuration

```text
docker compose run --rm --no-deps bot python -m bot.main --check
```

**Success** prints one line and exits `0`:

```text
… scheduler config_ok guild=123456789 timezone=America/Los_Angeles model=gemini-2.5-flash-lite mention_channels=0 context_limit=50
```

**Any problem** exits `2` and names what to fix:

| Message | Fix |
| --- | --- |
| `Missing configuration: DISCORD_TOKEN, …` | Fill the named keys in `.env` |
| `DISCORD_GUILD_ID must be the numeric guild ID.` | Use the numeric ID, not the server name |
| `Set ALLOWED_USER_IDS or ALLOWED_ROLE_IDS; …` | Grant at least one user or role (step 2) |
| `TEAM_TIMEZONE is not a known IANA zone: …` | Use a name like `America/Los_Angeles` |
| `CONTEXT_MESSAGE_LIMIT must be a whole number from 0 to 500.` | Fix the value |

This checks the bot's settings only. `docker compose config` validates the whole Compose file, including the dashboard's required variables.

### Step 7: Start Dobby and connect the services

```text
docker compose up -d --build
docker compose logs --tail 50 -f bot dashboard
```

`migrate` applies the database schema, then `bot`, `dashboard` and `frontend` start. **Expected:** the bot log shows `bot_ready guild=…` and slash commands appear in your server within a few seconds. If it repeats `startup_failed`, stop with `docker compose down` and rerun step 6.

Then, in a browser:

1. Open `DASHBOARD_URL` (default <http://localhost:3000>) and sign in with your local admin username/password or a pre-registered OAuth admin account, depending on `AUTH_MODE`.
2. **Users:** add teammates — display name, Google email, their Discord user ID (so `@mentions` and `/email` work) and their calendar email. Anyone can later change their own calendar email on the dashboard home page or with `/email` in Discord.
3. **Service accounts** (admin only): press **Connect** for Google Calendar, Notion, Instagram and LinkedIn. Each opens Composio's OAuth flow for that service under the `dobby` entity; approve it with the group's account and you land back on the page with a **Connected** badge.
4. In Discord, try `/help`, then `/events` — Dobby lists the connected calendar's upcoming events.

Run **one bot instance per Discord token**. Stop the Windows copy with `docker compose down` before starting a Pi copy.

## How to use Dobby

Type `@Dobby` and pick the bot from Discord's mention suggestions, or use a slash command. Dobby reads the last 50 human messages in that channel for context, replies in the channel (never by DM), and edits its reply when done.

### Meetings

```text
@Dobby schedule a Planning meeting tomorrow at 10am for 45 minutes
@Dobby move the release review to Thursday 3pm
@Dobby set up a design review Friday at 2pm and invite Maya and @Leonard
Teammate: let's do the launch checklist next Tuesday at 2pm
You: @Dobby make this a meeting
```

Meetings default to one hour in `TEAM_TIMEZONE`. Dobby matches a typed name against registered users' display names (exact, then first name, then a close match) and resolves `@mentions` directly; if someone has no calendar email on file it says so rather than guessing. `/events days:30` lists upcoming events.

### Notion

`/notion search query:onboarding` finds pages; `/notion note title:Standup 9/17 content:…` creates one (under `NOTION_PARENT_PAGE_ID` when set). Or just ask: `@Dobby add today's decisions to the Roadmap page`.

### Instagram and LinkedIn

```text
/linkedin post text:We shipped v2 today — thanks to everyone who tested!
/instagram posts                       → our recent posts, numbered
/instagram post image_url:https://… caption:Workshop night
/instagram story post:2                → put post #2's photo on our story
@Dobby draft a LinkedIn post about Friday's demo
```

Every one of these shows the exact text/image first with **Confirm** and **Cancel** buttons. Only the requester can press them, they expire after two minutes, and nothing is published until Confirm. Images must be public `https` URLs. A story "featuring" a post re-publishes that post's photo or video; Instagram's API cannot attach the tappable share sticker, and carousel posts cannot be reused.

### Your calendar email

`/email action:set email:you@uw.edu`, `/email action:show` (masked), `/email action:remove` — or edit it on the dashboard home page. You must be on the dashboard's user list with your Discord ID for `/email` to work.

### Slash command reference

| Command | Purpose |
| --- | --- |
| `/schedule request:…` | Create, move, rename or delete a meeting |
| `/events days:30` | Upcoming events |
| `/notion search query:…` / `/notion note title:… content:…` | Find Notion pages or create one |
| `/linkedin post text:…` | Preview a LinkedIn post; Confirm publishes it |
| `/instagram posts` / `post` / `story` | List our posts; post a photo; put a post or image on our story — all previewed, then Confirm |
| `/email action:set|show|remove` | Your own calendar email |
| `/help` | Every service's examples and privacy information |

Replies and previews are visible to everyone in the channel. Dobby never sends DMs.

## Everyday Docker commands

| Task | Command |
| --- | --- |
| Start/build everything | `docker compose up -d --build` |
| Status | `docker compose ps` |
| Follow bot logs | `docker compose logs --tail 50 -f bot` |
| Follow API logs | `docker compose logs --tail 50 -f dashboard` |
| Stop, keep data | `docker compose down` |
| Apply a changed `.env` | `docker compose up -d --force-recreate --no-build` (rebuild `frontend` if `API_URL` changed) |
| Apply source updates | `git pull --ff-only`, then `docker compose up -d --build` |
| Run migrations again | `docker compose run --rm migrate` |
| Check bot config | `docker compose run --rm --no-deps bot python -m bot.main --check` |
| Open a Postgres shell | `docker compose exec postgres psql -U dobby dobby` |
| View users and calendar emails | Dashboard → Users, or `docker compose exec postgres psql -U dobby dobby -c "select display_name, calendar_email from users"` |
| Back up the database | `docker compose exec postgres pg_dump -U dobby dobby > backup.sql` |
| Switch the bot to the published image (Pi) | `docker compose -f compose.yaml -f compose.registry.yaml pull bot`, then `… up -d --no-build --pull never bot` |
| Remove containers and local images | `docker compose down --rmi local` (add `-v` to delete the database too) |
| Run the test suite in Docker | `docker compose -f compose.test.yaml run --rm tests` |
| Run lint/format checks in Docker | `docker compose -f compose.test.yaml run --rm lint` |

Docker restarts the services after a reboot unless you stopped them. Windows Docker Desktop must stay running; sleep interrupts hosting.

## Test it in Docker

The test suite and lint need no credentials and run with networking disabled:

```text
docker compose -f compose.test.yaml run --rm tests
docker compose -f compose.test.yaml run --rm lint
```

Then validate `.env` without contacting Discord (step 6). Run it before the first `up`: the restart policy otherwise retries a misconfigured container forever.

## Automatic updates from GitHub

Pushes to `main` run the checks and publish `linux/amd64` and `linux/arm64` **bot** images to GitHub Container Registry using the built-in `GITHUB_TOKEN`. Make the package public for unauthenticated pulls. The optional Pi timer pulls and recreates the `bot` service when its image changes; see [automatic updates](docs/DEPLOYMENT.md#automatic-updates-on-the-pi). The dashboard and frontend images are built locally from the checkout.

## Secrets and access

- Credentials belong in local `.env`, which Git and Docker builds ignore. Only `.env.example` is tracked. Compose passes values to containers as environment variables; nothing is baked into images.
- Service tokens (Google, Notion, Meta, LinkedIn) live in **Composio**, under your Composio account, not on this machine. Rotating `COMPOSIO_API_KEY` or disconnecting a service in Composio cuts Dobby off immediately.
- The Postgres volume (`pgdata`) holds teammates' emails and dashboard sessions; treat database backups like `.env`. No message content is ever stored.
- On Pi keep `.env` at mode `600`, owned by the configured UID/GID. On Windows restrict the folder to your account. Compose secrets are not encrypted at rest; host root and Docker administrators can read them.
- Anyone with the allowed role can act on all connected services *through Dobby's accounts*: create calendar events, write Notion pages, and — after their own Confirm — publish to the group's Instagram and LinkedIn. Restrict who gets the role.
- Only dashboard admins can connect or disconnect services and edit other people's emails.
- Rotate leaked credentials immediately. Removing a file does not remove it from Git history; enable GitHub push protection.

## Limitations

- One bot instance, one Discord server, one Composio entity (one account per service).
- Confirm buttons and cooldowns live in the bot process; a restart discards pending previews.
- Instagram publishing requires a Business/Creator account and public image URLs; stories cannot carry the share sticker; carousels cannot be re-used.
- Composio action names are verified at startup, not at build time; a renamed action disables that capability until the list in `bot/integrations/<service>/__init__.py` is updated.
- Gemini quotas and data terms apply. Continuous outbound internet is needed; no inbound ports beyond the dashboard's 3000/8000 on your LAN.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Cannot connect to Docker | Start Docker Desktop/Engine; use Linux containers |
| `migrate` fails / bot cannot reach the database | `docker compose logs postgres migrate`; `POSTGRES_PASSWORD` must be set before the first start (changing it later requires `docker compose down -v`) |
| Repeated `startup_failed` in the bot | `docker compose down`, then step 6's `--check` |
| Bot starts but commands missing | Confirm `DISCORD_GUILD_ID`; commands sync to that one server on `bot_ready` |
| Gateway 4014 | Enable Message Content Intent in the developer portal |
| Mention ignored | Real mention, allowed role/user, allowed channel, 10-second cooldown; `mention_access_denied` in the logs says why |
| Replies have no context | Grant the bot Read Message History in that channel |
| `composio_action_unknown` in the bot log | Composio renamed an action; list current names (docs/BOT_ARCHITECTURE.md) and update the integration's `ACTIONS` |
| Tool calls fail with "no connected account" | Connect that service on the dashboard's Service accounts page; the entity must match `COMPOSIO_ENTITY_ID` |
| Dashboard login says not pre-registered | An admin must add the user (Google email or Discord ID) first; OAuth bootstrap uses `BOOTSTRAP_ADMIN_EMAIL` only when no admin exists; local admins use the CLI in Step 5 |
| Local username/password rejected | Check `AUTH_MODE=local` or `both`; reset with `docker compose exec dashboard python -m dashboard.local_admin USERNAME`. After five attempts, wait one minute. |
| Dashboard unreachable from another computer | Use the server LAN IP in both URL variables, rebuild/recreate `frontend`, and allow TCP 3000/8000 from your local subnet. Use the same frontend origin as `DASHBOARD_URL`. |
| Login method disabled / old session rejected | Switching `AUTH_MODE` disables sessions from the excluded provider; sign in again using an enabled method. |
| Google login rejected | Use a verified, pre-registered Google email and an External OAuth audience; redirect URI must be `API_URL/auth/google/callback` |
| Connect button returns to Composio's page, no "Connected" badge | The Composio redirect points at the API's `/integrations/<provider>/callback`; `API_URL` must be reachable from the browser |
| Frontend calls the wrong API host | `API_URL` is baked at build time: `docker compose build frontend && docker compose up -d frontend` |
| Instagram commands say `INSTAGRAM_USER_ID is not set` | Set it in `.env` and recreate the bot |
| Instagram/LinkedIn publish fails | Check the connection in Composio (scopes, token expiry) and the audit log on the dashboard |
| Registry pull denied | Make the package public and use a lowercase `DOBBY_IMAGE` |

## Development

Python 3.12 (the Docker image's version; `composio-core`'s dependencies do not build on 3.14 yet) and Node 20:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt -r dashboard/requirements.txt pytest
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\ruff check bot scripts tests
.\.venv\Scripts\ruff format --check bot scripts tests
cd frontend; npm install; npm run lint; npm run build
```

On Pi/Linux use `.venv/bin/python`. Tests mock Discord, Gemini, Composio and the database; live testing needs your credentials. Dobby's phrasings live in `bot/responses/*.txt` (20 lines per file, checked by the suite). To add a service, create a folder under `bot/integrations/` — see [docs/BOT_ARCHITECTURE.md](docs/BOT_ARCHITECTURE.md#adding-or-changing-an-integration).
