# Talaria Maintainer Guide

This guide describes how the Talaria WebUI repository is organized, how a browser request moves through the application, where state lives, and how to change and verify behavior safely. It supplements the user-facing [README](../README.md) and contributor workflow in [CONTRIBUTING.md](../CONTRIBUTING.md). When code and this document disagree, the code is authoritative; update this guide when an ownership boundary or workflow changes.

## 1. Product and architectural boundaries

Talaria is a thin web interface and integration layer for Hermes Agent. It connects to Hermes through its public HTTP API. Talaria does not import Hermes internals in its backend API client (`src/talaria/hermes.py`). Keep responsibilities explicit:

- Hermes owns agent execution, conversation transcripts, sessions and runs, model/provider behavior, and authorization for its own resources.
- Talaria owns browser authentication, multi-user assignments and roles, presentation, its UI, proxying/adaptation of Hermes API behavior, and small client-specific records Hermes does not persist for Talaria.
- The browser owns transient presentation state and unsent drafts. It must not be treated as the durable authority for user, profile, session, run, or billing access.

A typical request path is:

```text
Browser modules
  -> same-origin /api/* request (credentials + Talaria request marker + CSRF token)
  -> SecurityHeaders / PublicPath / BrowserBoundary / Compression middleware
  -> Starlette route in app.py
  -> route/domain module
  -> selected profile's Hermes client, local store, or both
  -> JSON or streamed event response
```

Profile selection is per request/tab, not global shared state. `ProfileRouter` selects the profile app; profile-aware modules resolve the current app from the request. For regular users, server-side authorization and the assigned profile remain authoritative even if the browser changes query parameters or submits a different profile.

## 2. Repository map

### Python application (`src/talaria/`)

- `app.py`: ASGI application factory, route table, middleware boundary, exception handling, lifespan initialization and shutdown. Start here to understand exposed HTTP routes and shared app state.
- `cli.py`: command-line entry point and server startup; handles `--config`, `--host`, `--port`, `--public-url`, `--dev`, password setup, and dispatches management commands.
- `server.py`: Uvicorn integration and graceful shutdown of long-lived streams.
- `config.py`: `Settings`, default config path, URL validation, atomic JSON persistence.
- `auth.py`, `auth_sessions.py`: password hashing/verification, signed cookies, CSRF/origin checks, login throttling, and revocation tracking.
- `users.py`: durable user database, roles, profile assignment, per-user budget and presentation, session/run ownership records.
- `profiles.py`: saved Hermes connections, per-profile app/client lifecycle, profile routing and connection mutations.
- `hermes.py`: bounded HTTP client and public Hermes API contract; URL/profile normalization, response decoding, errors, stream limits.
- `relay.py`: event relay between Hermes runs and browser subscribers; owns stream coordination, replay, and notifications.
- `routes.py`: primary API handlers: login/bootstrap, connection, profiles/users-related controls, sessions/messages, run start/control/events, fork/reply, budgets, and presentation.
- `session_views.py`: session search, activity and history-window views.
- `session_commands.py`: Talaria-owned command records, execution lifecycle and command followers.
- `session_state.py`: SQLite state for commands and per-session model/reasoning preferences that Hermes does not store for this client.
- `session_preferences.py`: session preference update/import operations.
- `branching.py`: branch-point discovery and session branching helpers.
- `transcripts.py`: transcript export.
- `uploads.py`: raw non-image file upload and cancellation/delete handling. Uploads are stored beside the active config at `uploads/<session-id>/<filename>`; location is currently not configurable.
- `artifacts.py`, `artifact_routes.py`: Talaria's profile-scoped artifact metadata and download routes. Do not confuse artifacts with user-uploaded input files.
- `budget.py`: usage windows, cost snapshots, reset values and budget parsing; route admission enforcement lives in request/run handling.
- `branding.py`, `agent_presentation.py`: branding packs and validated assistant name/icon presentation.
- `push.py`: Web Push subscription storage, payloads and service-worker route. Live in-page run events still use the relay/stream route.
- `metadata.py`: agent information and readiness projection/filtering.
- `extensions.py`: optional Hermes plugin capability discovery and session extensions with native API fallbacks where supported.
- `web.py`: static asset routing, response headers, compression support, health and index responses.
- `proxy.py`: reverse-proxy base-path handling.
- `setup*.py`, `installation.py`, `deployment.py`, `supervisor*.py`, `maintenance.py`, `updates.py`, `uninstall.py`: install, managed deployment, update, rollback and service lifecycle. Read the relevant command path before changing installation behavior.
- `hermes_plugin/`: optional plugin installed into Hermes. It is a separate integration component; its data disclosures are documented in `hermes_plugin/README.md`.

### Browser application (`src/talaria/static/`)

- `index.html`, `app.js`: HTML shell and Preact application composition.
- `boot.js`, `startup.js`: startup loading, retry, and failure recovery.
- `api.js`: same-origin API client, request headers, error normalization, and upload transport/progress.
- `store.js`: shared browser state and session/profile navigation actions.
- `runs.js`: run creation, stream/event handling, stop/guidance/recovery and transcript updates.
- `composer.js`, `attachments.js`, `images.js`: message composition, image preparation, generic file upload, progress/status, and cancellation.
- `conversation.js`, `content.js`, `response-parts.js`, `markdown*.js`, `stream-reveal.js`: rendering messages, content parts, streamed Markdown and source identity.
- `sidebar.js`, `session-navigation.js`, `session-search.js`, `history-page.js`, `history-anchor.js`: session list/navigation/history.
- `settings.js`, `dialogs.js`, `appearance.js`, `profiles.js`, `access-settings.js`, `budget-ui.js`: settings and account/profile UI.
- `notifications.js`, `push.js`, `page-lifecycle.js`: foreground/background notifications and lifecycle behavior.
- `i18n.js`, `language.js`, `locales/*.json`: translation lookup and catalogs.
- `styles/`: authored CSS, separated by layout, chat, dialogs, settings, theme, responsiveness, and conversation features.
- `vendor/`: pinned browser libraries and licenses. Update through the documented vendor workflow, not by editing generated/minified files by hand.
- `built/`: generated production bundles, source maps, manifest and styles. Commit regenerated outputs with source changes; never use this directory as the source of truth.

### Tests and developer tooling

- `tests/test_*.py`: Python unit, integration and browser tests.
- `tests/conftest.py`, `tests/fake_hermes.py`: fixtures and deterministic fake Hermes server/client support.
- `tests/hermes_*_contract.py`: optional tests against a native Hermes checkout for public-contract compatibility.
- `tests/fixtures/`: recorded Hermes response fixtures; see `tests/fixtures/README.md` before changing them.
- `contrib/check.py`: orchestrates project checks. Use `--help` for supported modes and flags.
- `contrib/build.mjs`: frontend compilation, bundling, production asset generation and validation.
- `contrib/i18n.mjs`: translation extraction and catalog validation.
- `contrib/quality.py`, `contrib/perf.py`, `contrib/install_walkthrough.py`: quality, performance and install lifecycle tooling.

## 3. Startup, application state and shutdown

`talaria` enters through the console script declared in `pyproject.toml` (`talaria.cli:main`). The default config path is computed by `config.default_path()` as `$XDG_CONFIG_HOME/talaria/config.json`, or `~/.config/talaria/config.json` when `XDG_CONFIG_HOME` is unset. CLI flags may override bind/public URL/config behavior. Development mode uses a separate config and port.

`create_app()` in `app.py` assembles the Starlette application. It creates stores and clients, mounts routes, and installs middleware. At startup, the lifespan resumes durable command followers; shutdown closes followers and profiles and stops streams before the server drains outstanding requests. Avoid adding work to import time when it belongs in the factory or lifespan.

Important per-app state includes settings/config path, users, Hermes client/key, login limiter, profiles, relay, session state, artifacts, push store and capability information. A profile router can reuse a shared session-state store and command followers. Keep profile-specific values (Hermes URL/key, profile ID, profile presentation) separate from shared Talaria state.

`BrowserBoundary` enforces authentication on private `/api/*` requests and validates unsafe browser requests. `SecurityHeaders`, `PublicPath`, profile routing and compression are separate middleware layers. When debugging a request rejected before reaching a route, inspect middleware ordering and the response code before changing route logic.

## 4. Request and run lifecycle

### Normal page/API request

1. Browser boot loads the production shell or source modules in development.
2. `Startup` calls store initialization and retries when connectivity returns or the page becomes active.
3. `api.js` sends same-origin requests with cookies. Unsafe requests include `X-Talaria-Request: 1` and the CSRF token. Do not bypass this client for browser mutations.
4. `BrowserBoundary` checks login and browser request validity; profile routing selects the proper Hermes app.
5. A route validates input, checks authorization/ownership/budget where relevant, then calls a domain module or Hermes.
6. The route returns JSON, a file response, or a long-lived event stream. Errors should use the established `APIError` shape rather than leaking internal exception text.

### Message/run flow

The browser composer gathers text and prepared images, ensures selected generic files have completed upload, then calls the run API. `routes.start_run` is the admission boundary: validate payload and ownership, enforce capacity/budget conditions, then start or attach to a run. `Relay` coordinates Hermes events, subscriber replay and push notification callbacks. The browser's `runs.js` reconciles events with run status/history to handle reconnects, gaps and interrupted requests. Do not equate “HTTP request returned” with “run completed”; test event-stream completion and recovery behavior.

### Generic file attachments

Non-image files are stored byte-for-byte by Talaria; there is no extractor. The server enforces the configured code constants in `uploads.py` (currently 25 MiB per file) and safe filenames. It creates the upload folder beside the config, then a session-ID child folder. The upload response includes a unique ID, final filename (may gain a collision suffix), absolute path, relative path, MIME, byte size and session ID.

The frontend keeps pending files in composer state. Upload progress is displayed per file. Hermes receives metadata and a Talaria-generated hidden context block, not the file bytes. Removing a pending file removes it locally. Removing an uploaded file sends `DELETE /api/sessions/{session_id}/upload` with the stored filename; the chip is removed only after deletion succeeds. Server deletion is constrained to that session's upload directory. Do not use a user-supplied absolute path as a deletion target.

The context instructs the agent to treat filenames/content as untrusted reference data, copy the upload before processing, preserve the original, and work on the session copy. This is an agent instruction, not a sandbox. Talaria's current upload path is derived from the config directory and has no separate configurable upload-root setting.

## 5. Persistence and ownership

Persistence is deliberately split by authority:

- `config.json`: connection, listener/public URL, authentication/signing settings, trusted proxies and branding path. `config.py` saves atomically.
- `profiles.json`: saved Hermes connections and their presentation metadata; credentials are private server-side data.
- `config.users.db`: users, role/profile assignment, user budgets/presentation, and session/run ownership records. Created by `UserStore` beside the config.
- `config.sessions.json`: hashed session-cookie revocations, so explicit sign-out remains effective across restarts.
- `config.state.db`: Talaria command history and per-session model/reasoning choices (`SessionState`).
- `config.artifacts.db`: local artifact metadata, with profile scoping.
- `config.push.db` (or the path used by `PushStore`): push subscription state.
- `uploads/<session-id>/`: user-supplied raw files, colocated with config; canceled uploads are deleted through the session-scoped route.
- Hermes storage: transcripts, run/session state and agent workspace. Talaria does not set Hermes's workspace root.

Use actual code paths when changing filenames or store layout; this list follows current default names. Existing state schema changes need migration/versioning and tests for existing databases. Keep secrets, message bodies, uploaded file contents and credentials out of logs and tests unless a test uses synthetic data.

For multi-user access, a regular user is assigned one Hermes profile; administrators can manage users and access profiles. Talaria tracks ownership records for relevant resources, but Hermes remains responsible for its own session/run authority. Apply authorization at the server route, not only by hiding UI controls. Test both regular-user and admin behavior.

## 6. Security and reliability invariants

Preserve these properties when refactoring:

- Browser write routes require authenticated cookies, same-origin/fetch checks and CSRF validation.
- Secrets are not returned by profile/connection APIs and must not be committed or printed.
- Validate identifiers, filenames, payload shapes and bounded sizes before upstream calls or disk writes.
- File deletion is session-scoped, filename-validated and rooted beneath that session's upload directory. No path supplied by the browser should be trusted as a filesystem path.
- Treat all user/agent/file text as untrusted. Escape or sanitize rendered content; never execute Markdown/HTML from an untrusted source.
- Streams and upstream JSON have explicit size/concurrency bounds. Cancellation and shutdown must release clients, locks, admissions and subscriptions.
- Keep async I/O nonblocking where practical; preserve task cancellation instead of swallowing it.
- Avoid global mutable state for profile selection or user context.
- Persistence must be atomic or transactional where multiple fields must remain consistent. New DB fields require a migration path.
- Error messages returned to browsers should be actionable but not disclose credentials, filesystem internals, or full upstream payloads.

## 7. Frontend behavior and build discipline

Source JavaScript uses Preact and `htm` templates. Components should keep state close to the feature, use shared store actions for cross-screen state, and route network calls through `api.js`. `store.js` owns navigation/state transitions; `runs.js` owns stream lifecycle; avoid duplicating run state in components.

Use localization helpers for user-visible text. `contrib/i18n.mjs --extract` collects source messages; catalogs live in `src/talaria/static/locales/`. Keep placeholders unchanged and validate every catalog. Do not localize Hermes-generated content, commands, model identifiers or filesystem paths.

After any frontend source/vendor/build-tool change:

```sh
npm run build
node contrib/build.mjs --check
```

Generated output under `static/built/` is committed. Do not hand-edit it. For a visible UI change, add or update a browser test and inspect an actual screenshot when layout/interaction is material; DOM-only assertions do not catch visual regressions.

## 8. Tests and validation

First install the pinned development environment as documented in `CONTRIBUTING.md`:

```sh
uv sync --locked
npm ci
uv run --locked playwright install --with-deps chromium firefox webkit
```

Use the narrowest relevant test while iterating, then expand:

```sh
uv run pytest tests/test_app.py -q
uv run pytest tests/test_multi_user.py -q
uv run pytest tests/test_conversation_features.py -q
uv run pytest -m browser -q
uv run pytest -q
```

The available project check driver is:

```sh
uv run --locked python contrib/check.py --help
uv run --locked python contrib/check.py check --changed
uv run --locked python contrib/check.py full --revision HEAD
```

Frontend checks:

```sh
npm run lint
npm run build
node contrib/build.mjs --check
node contrib/i18n.mjs --check
```

Use `tests/fake_hermes.py` for deterministic API and stream behavior. Native Hermes contract tests require the Hermes checkout and environment described in `CONTRIBUTING.md`; do not make ordinary tests depend on a developer's live account or API credentials. For browser behavior, use `page` fixtures and existing authenticated app fixtures. Keep tests deterministic and isolate filesystem state with temporary directories.

When a feature crosses browser → Talaria route → filesystem/Hermes, include an integration test at that seam. For authorization or profile behavior, test the allowed and denied cases. For UI state transitions, test pending, success, failure, retry/cancel and the visible result. When changing a protocol, update contract tests and fixtures deliberately.

## 9. Safe change workflow

1. Confirm the working tree and current branch before editing. Read the owning module and its callers/tests.
2. Identify the authoritative owner for the behavior: Hermes, Talaria backend, browser, or installer.
3. Write a focused test for the intended behavior and run it to observe the expected failure.
4. Implement the smallest change in the owning module. Keep the API contract and security boundary explicit.
5. Run focused tests, then relevant broader tests, lints, localization and asset checks.
6. For user-visible changes, verify the browser interaction and screenshot. For integration changes, exercise the real Talaria server or the project’s app fixture as appropriate.
7. Review `git diff --check`, generated outputs and the full diff. Update this guide and README/CONTRIBUTING if behavior/workflow changed.
8. Commit with the repository's Conventional Commit convention. Push/deploy/restart only when requested or explicitly part of the task; verify external effects before reporting them.

Avoid broad cleanup bundled with a feature. Preserve unrelated working-tree changes. Do not restart Hermes to apply a Talaria-only change.

## 10. Troubleshooting map

- App won't start: `cli.py`, `config.py`, `server.py`, then `app.py` lifespan and Uvicorn log.
- Browser gets 401/403 before route: `BrowserBoundary`, `auth.py`, CSRF headers in `static/api.js`, reverse-proxy origin/base path.
- Wrong user/profile sees a session: trace `ProfileRouter`, `routes.py` authorization and `UserStore` ownership; never patch only the picker UI.
- Run appears stuck or stream disconnects: `routes.events`, `relay.py`, `hermes.py` stream limits and browser `runs.js` reconciliation.
- Attachment missing or stale: `uploads.py`, `composer.js` upload state, `api.js` progress transport; verify returned `session_id` and final filename.
- Attachment cancel leaves a chip: inspect the DELETE response and `removeFile()` error path. A chip should remain if backend deletion fails.
- UI source works but production differs: rebuild `static/built/` and run `node contrib/build.mjs --check`.
- Translation check fails: extract source messages, update catalogs, run `node contrib/i18n.mjs --check`.
- State database unavailable: `session_state.py`, `StateUnavailable` handler, file permissions and schema version. Do not delete user data to make a test pass.

## 11. Keeping this guide accurate

This guide is intentionally an architectural index, not a frozen API specification. When adding a new subsystem:

- Add its module to the repository map and describe the owner/data boundary.
- Document persistent files, migration/retention behavior and any size/concurrency limits.
- Explain the route or event flow and point to its tests.
- Record security invariants and operational recovery steps.
- Link detailed feature docs rather than duplicating long specifications.

Recheck file paths and constants against the current source before copying snippets into issues or operational runbooks.
