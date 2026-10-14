# Social Media Session Monitoring Dashboard

This is a local FastAPI dashboard I built to keep track of accounts and sessions in the application, and to review limited browser activity when a person chooses to pair and enable the Chrome extension. It also includes a post-reach comparison view. The browser records show activity on supported domains; they do not establish that someone signed in to a social-media account.

## What it does

- Lets people register, sign in, and sign out of this application. Passwords are stored as Argon2 hashes rather than plain text.
- Records application login/logout events (including login success or failure where available) with an account label, event type, source, confidence, and timestamp. Sessions include creation, last-activity, expiry, and revocation timestamps; account details derive last-login and last-logout times from the activity records.
- Provides an administrator-only user directory, account details and activity history, and account activation controls.
- Shows the signed-in user's Login Activity and session information, with filters for the available activity fields.
- Supports optional, consent-based browser activity tracking through a Chrome Manifest V3 extension. Stored events include a supported domain, event type, occurrence/recording timestamps, optional duration, consent version, and limited metadata.
- Includes session inventory and network-observation views. Network capture is off by default.
- Compares a post's reach with a baseline from earlier posts for the same connected account.

## Browser activity is not a login record

The extension observes browser navigation and tab activity on supported domains. A visit, tab switch, or time spent on a domain does **not** prove that a person logged in or out of Facebook, Instagram, or another site. The application can confirm its own login and logout events; it does not reliably observe authentication events on third-party websites.

The extension is opt-in: it must be paired with the dashboard and monitoring must be enabled in its popup. It reports a normalized domain and limited event metadata, not full URLs or page contents. It does not read passwords, form contents, cookies, access tokens, or browser session credentials. See [browser-extension/README.md](browser-extension/README.md) for pairing and revocation steps.

## Post-reach diagnosis and data source

The diagnosis view uses metrics stored by this application. For a diagnosis, it takes the latest post record as the post being assessed, excludes that record from the historical baseline, filters historical reach outliers using the 1.5-IQR rule, and compares the latest reach with the median of the remaining comparable posts when that latest post has reach data. It needs at least two comparable historical posts to produce a baseline. If there is not enough data, the response reports that limitation instead of presenting a made-up comparison.

The project does **not** currently retrieve live Facebook or Instagram post metrics end to end. The social connection flow is a demo/placeholder flow, and the included sample metrics are synthetic and marked as demo data. A configured app ID or a browser visit is not evidence of an authorized provider connection. The diagnosis logic works with the application's expected metric records, but live provider data has not been verified.

## Technology

- Python, FastAPI, Pydantic Settings, SQLAlchemy, and SQLite
- HTML, CSS, and vanilla JavaScript for the dashboard
- Chrome Manifest V3 APIs for the optional extension
- Pytest for the Python suite and Node's built-in test runner for extension tests
- Docker Compose for containerized local startup

## Run locally on Windows

Use PowerShell from the project root. Python 3.12 is the version used by the Docker image.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The API's interactive documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). The default SQLite database is `data/app.db`; the application initializes its schema at startup. Keep that file if you need to retain local data.

### Configuration and first administrator

The application reads settings from environment variables and, when present, `.env`. Start with `.env.example`; do not commit a `.env` file or database containing private data.

`INITIAL_ADMIN_USERNAME` is an optional one-time bootstrap setting. Set it to the exact username of an already registered, active account before the first administrator bootstrap. It must match exactly one active account; it is not a way to grant admin privileges during public registration. Leave it unset when you do not need to bootstrap an administrator. The normal registration form does not accept a role.

Other settings in `.env.example` include the SQLite URL, session cookie and lifetime settings, observation retention, network-capture controls, and Meta OAuth demo settings. Network capture and Meta demo mode are configured off/on respectively by default; review the example file before changing them.

## Chrome extension

To load the extension locally:

1. Start the dashboard using the instructions above.
2. In Chrome, open `chrome://extensions`, enable **Developer mode**, and select **Load unpacked**.
3. Choose the repository's `browser-extension` folder.
4. Sign in to the dashboard, then start pairing from the dashboard's Monitoring view (or the documented pairing endpoint).
5. Enter the short-lived pairing code in the extension popup. Pairing alone does not start collection; explicitly enable monitoring in the popup.
6. Check browser activity in the dashboard's Monitoring and Login Activity views.
7. To stop collection, pause or disconnect in the popup. To invalidate the device at the server, use **Revoke device** in the dashboard. Disconnecting locally is not the same as server-side revocation.

The extension's supported domains, permissions, event fields, consent behavior, and errors are described in [browser-extension/README.md](browser-extension/README.md).

## Dashboard sections

- **Login Activity** — application authentication events and consented browser events, with browser events identified as observed activity rather than confirmed website authentication.
- **Sessions** — the current user's application sessions and their active, expired, or revoked state.
- **User Directory** — administrator-only listing, user details, account timestamps/activity, and activation controls.
- **Monitoring** — paired extension devices, consent state, browser activity, and network observations when enabled.
- **Social Accounts / Diagnosis** — demo connection and stored post metrics, plus the historical reach comparison described above.

## API overview

The API is served by the same FastAPI application. See `/docs` for request and response schemas.

| Area | Routes |
| --- | --- |
| Authentication | `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me` |
| Application sessions | `/sessions`, `/sessions/stats`, `/sessions/events`, `/sessions/{session_id}`, `/sessions/{session_id}/revoke` |
| Session inventory | `/session-inventory` and its stats, refresh, and revoke routes |
| Login Activity | `/login-activity/events`, `/login-activity/stats` |
| Administrator user management | `/users`, `/users/{user_id}/details`, `/users/{user_id}/status` |
| Browser extension and activity | `/browser-extension/pairing/start`, `/browser-extension/pairing/exchange`, `/browser-extension/devices`, `/browser-activity/*` |
| Monitoring | `/monitoring/network`, `/monitoring/network/stats`, `/monitoring/consent`, `/monitoring/connections` |
| Social data and diagnosis | `/social/connections`, `/social/analytics/demo`, `/social/analytics/posts`, `/social/analytics/diagnosis` |

Protected routes use the application's authenticated session. User-directory and account-status management are restricted to administrators. Public registration does not grant an administrator role.

## Tests

From the project root, run the Python tests with the configured virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Run the extension tests from its directory (Node.js must be installed):

```powershell
Set-Location browser-extension
npm test
Set-Location ..
```

## Docker

With Docker Desktop running, build and start the application from the project root:

```powershell
docker compose up --build
```

Docker Compose stores the SQLite database in the named `app-data` volume. Stop the application with `Ctrl+C`; `docker compose down` stops and removes the container, not the named data volume.


