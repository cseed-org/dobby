# Dashboard API — Architecture

The dashboard is a FastAPI service that backs the Next.js web dashboard (`frontend/`).
It handles UW-Google and Discord login, each user's calendar email, admin management of users, guild
settings and the audit log, and the admin-only Composio connections for Dobby's own service accounts. It uses the same Postgres database as the Discord bot (`bot/`).

## Module map

| File | Role |
|---|---|
| `main.py` | Builds the FastAPI app: lifespan, middleware, routers, `/health`, `GET /me`, `PATCH /me` (own calendar email) |
| `auth.py` | Signs session tokens, sets the cookie, stores sessions, provides the `get_current_user` / `require_admin` dependencies |
| `database.py` | Async SQLAlchemy engine (`pool_size=5`, `max_overflow=2`), `SessionLocal`, `Base`, `get_db` dependency |
| `models.py` | ORM models: `User`, `Session`, `Integration`, `AgentAction` |
| `schemas.py` | Pydantic v2 request/response models, the paginated wrappers, and `clean_email()` validation shared by every email field |
| `seed.py` | `seed_bootstrap_admin()`: creates the first admin at startup |
| `routers/auth.py` | Google and Discord OAuth login (authlib) and logout |
| `routers/admin.py` | Admin-only endpoints for users (create, edit, role, delete), guild settings and the audit log |
| `routers/integrations.py` | Admin-only Composio connect, callback, list and disconnect for the single service entity |
| `requirements.txt` | fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, authlib, httpx, pydantic, python-dotenv, itsdangerous, composio-core |
| `Dockerfile` | python:3.12-slim image that runs `uvicorn dashboard.main:app` on port 8000 |

## Startup and wiring (`main.py`)

1. **Lifespan:** runs `seed_bootstrap_admin()` on startup and `engine.dispose()` on shutdown.
2. **`SessionMiddleware`** (signed with `SECRET_KEY`; `https_only` when `ENV=production`). authlib needs it to keep OAuth state. It is separate from the app's own login cookie.
3. **`CORSMiddleware`** allows a single origin, `DASHBOARD_URL`, with credentials and all methods and headers.
4. **Routers:** `auth` at `/auth`, `admin` at `/admin`, `integrations` at `/integrations`.
5. The app reads `SECRET_KEY` and `DATABASE_URL` with `os.environ[...]` when it is imported, so it will not start without them.

## Authentication and authorization

- **Login:** OAuth only. There are no passwords and no self-signup.
  - **Google** (`openid email profile`, `hd=uw.edu`): the callback checks that `userinfo.hd == "uw.edu"`, then looks up `users.uw_email`.
  - **Discord** (`identify email`): the callback calls `https://discord.com/api/users/@me` with httpx, then looks up `users.discord_id`.
  - If no matching user row exists, login returns **403**. An admin must add the user first.
- **Session token:** `itsdangerous.URLSafeSerializer(SECRET_KEY, salt="session").dumps(user_id)` plus `"." + token_hex(16)`.
  - The token is stored in `sessions` with its `provider` and `expires_at = now + 7 days`.
- **Cookie:** `dobby_session`, set with `HttpOnly`, `SameSite=Lax`, `Secure` when `ENV=production`, `max_age` of 7 days and `path=/`.
  - After login the API redirects to `{DASHBOARD_URL}/dashboard`.
- **`get_current_user`:** reads the cookie, checks the signature, then looks for a `sessions` row with this token that has not expired, then loads the `User`. Any failure returns **401**.
- **`require_admin`:** requires `user.role == "admin"`, otherwise returns **403**. There are two roles, `admin` and `student` (the default).
- **Logout:** deletes the session row, clears the cookie and redirects (302) to `{DASHBOARD_URL}/login`. Expired session rows are never cleaned up.

## API routes

| Method | Path | Auth | Purpose |
|---|---|---|---|
| **meta** | | | |
| GET | `/health` | none | Liveness check; returns `{"ok": true}` |
| GET | `/me` | user | Current user (`UserOut`) |
| PATCH | `/me` | user | Set or clear your own `calendar_email` (validated; empty clears) |
| PATCH | `/me` | user | Set or clear your own `calendar_email` (validated; empty clears) |
| **auth** (`routers/auth.py`) | | | |
| GET | `/auth/google` | none | Redirect to Google OAuth, limited to the `uw.edu` domain |
| GET | `/auth/google/callback` | none | Exchange the code, match `uw_email`, create a session, set the cookie, redirect |
| GET | `/auth/discord` | none | Redirect to Discord OAuth |
| GET | `/auth/discord/callback` | none | Exchange the code, fetch the Discord user, match `discord_id`, create a session, redirect |
| POST | `/auth/logout` | cookie | Delete the session, clear the cookie, redirect to `/login` |
| **admin** (`routers/admin.py`) | | | |
| GET | `/admin/users?limit&offset` | admin | Paginated user list, newest first (`{total, items}`; limit ≤ 200) |
| POST | `/admin/users` | admin | Pre-register a user; 409 if the email exists; sets `added_by` |
| PATCH | `/admin/users/{user_id}` | admin | Edit `display_name`, `discord_id`, `calendar_email` (only fields sent) |
| PATCH | `/admin/users/{user_id}` | admin | Edit `display_name`, `discord_id`, `calendar_email` (only fields sent) |
| DELETE | `/admin/users/{user_id}` | admin | Delete a user (not yourself); 204 |
| PATCH | `/admin/users/{user_id}/role` | admin | Set the role to `admin` or `student` |
| GET | `/admin/audit?limit&offset&tool&status` | admin | Paginated `agent_actions` (limit ≤ 500), written by the bot; tool name, status and timing only |
| **integrations** (`routers/integrations.py`) | | | |
| GET | `/integrations` | admin | Providers connected for Dobby's service entity |
| GET | `/integrations/{provider}/connect` | admin | Start a Composio connection for `COMPOSIO_ENTITY_ID` and redirect to it; 503 if no API key |
| GET | `/integrations/{provider}/callback` | admin | Upsert the provider's `integrations` row (`connected_by` = admin), then redirect to `/dashboard/integrations` |
| DELETE | `/integrations/{provider}` | admin | Remove the local integration row; 204 (it does not revoke the connection in Composio) |

Supported providers are `google_calendar`, `notion`, `instagram` and `linkedin` (one folder each under `bot/integrations/`). Admin and integration handlers log unexpected DB or Composio errors and return a generic 500 or 502.

## Data model (Postgres, shared with the bot)

- **`users`** (UUID PK): `uw_email` (unique), `discord_id` (unique), `display_name`, `calendar_email` (the address Dobby invites; nullable), `role`, `added_by` → `users.id`, `created_at`. Users can exist without login identifiers as directory-only entries (former contacts).
- **`sessions`** (UUID PK): `user_id` → `users` (cascade delete), `token` (unique), `provider`, `expires_at`.
- **`integrations`** (UUID PK): `provider` (unique), `composio_entity_id`, `connected_by` → `users.id` (set null on delete), `connected_at`. One row per provider for the service entity.
- **`agent_actions`** (bigint PK): audit rows for tool calls, metadata only (`user_id`, `discord_id`, `guild_id`, `channel_id`, `tool`, `status`, `duration_ms`). No tool arguments or results are kept, so no message content reaches the database. The bot writes it; the dashboard only reads it.
- The only ORM relationship is `User.sessions` (`cascade="all, delete-orphan"`).

## Seeding and migrations

- **Seeding:** at startup, if `BOOTSTRAP_ADMIN_EMAIL` is set and no admin exists, the app inserts an admin user with that email. `display_name` is the part of the email before the `@`.
- **Migrations:** the dashboard does not create or change the schema. The schema comes from Alembic in the repo-root `migrations/` (`versions/001_initial.py`, then `002_merge_contacts_service_integrations.py`, which folds `contacts` into `users.calendar_email`, drops `conversation_history` and `user_facts`, and makes `integrations` per provider).
  - Alembic runs in the compose `migrate` service, which is built from the root `Dockerfile` `migrate` target.
  - `env.py` removes `+asyncpg` from `DATABASE_URL` and sets `target_metadata=None`, so there is no autogenerate from these models.
- The migration is stricter than `models.py`. For example, it makes `display_name` and `sessions.provider` `NOT NULL`, while the ORM declares them nullable. Bot configuration is environment-only; there is no settings table.

## Configuration (environment variables)

| Variable | Used for |
|---|---|
| `DATABASE_URL` | **Required.** Async SQLAlchemy URL (`postgresql+asyncpg://...`) |
| `SECRET_KEY` | **Required.** Signs session tokens and the Starlette session |
| `ENV` | When set to `production`: `Secure` cookies and `https_only` sessions |
| `DASHBOARD_URL` | Frontend origin for CORS and redirect targets (default `http://localhost:3000`) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | Discord OAuth |
| `COMPOSIO_API_KEY` | Integrations; the connect route returns 503 if it is empty |
| `COMPOSIO_ENTITY_ID` | The service entity the connections belong to (default `dobby`); must match the bot |
| `COMPOSIO_ENTITY_ID` | The service entity the connections belong to (default `dobby`); must match the bot |
| `BOOTSTRAP_ADMIN_EMAIL` | Optional first-admin seed |

## Running

- **Docker:** `dashboard/Dockerfile` copies the package into `/app/dashboard/` so the relative imports resolve, then runs `uvicorn dashboard.main:app --host 0.0.0.0 --port 8000`.
- **Compose (`compose.yaml`):** the `dashboard` service builds `./dashboard` and publishes port `8000:8000`.
  - It waits for `migrate` to finish, and `migrate` waits for `postgres` to be healthy.
  - Compose requires the env vars listed above (`ENV` is not set there).
- **Frontend:** the `frontend` service calls this API from the browser with `credentials: 'include'`, using `NEXT_PUBLIC_API_URL` (see `frontend/src/lib/api.ts`).
- **Local development:** from the repo root, set the env vars and run `uvicorn dashboard.main:app --port 8000`.

## Notes and inconsistencies seen in the code

- Two URL variables: `DASHBOARD_URL` is the frontend origin (CORS, post-login redirects, used by this API); `API_URL` is the API's public address, which `compose.yaml` bakes into the frontend as `NEXT_PUBLIC_API_URL`. OAuth redirect URIs (`/auth/*/callback`, `/integrations/*/callback`) are built with `request.url_for`, i.e. from the host the browser actually used.
- The Composio connect flow passes `redirect_url` = this API's `/integrations/{provider}/callback`, so the `integrations` row is written when the browser returns; the row is still not verified against Composio's connection status.
- `/integrations/{provider}/callback` only records the row locally. It does not check the connection status with Composio.
