# Social Media Activity Monitor extension

See the root [README.md](../README.md) for the complete project setup,
architecture, API summary, privacy boundaries, and Docker instructions.

This is a minimal Chrome Manifest V3 extension for the existing local FastAPI browser-activity API. It is disabled until the user explicitly enables monitoring.

## What it collects

When enabled and paired, the extension sends only:

- A normalized supported domain name (`facebook.com`, `instagram.com`, `linkedin.com`, `tiktok.com`, `x.com`, or `youtube.com`)
- Navigation, tab activation/deactivation, and estimated active-tab duration events
- A small event type/transition or tab identifier metadata value
- A timestamp, consent version, and idempotency key

It does **not** collect full URLs, paths, query strings, fragments, page contents, messages, cookies, passwords, form inputs, request contents, access tokens, or browser session credentials. It does not detect successful logins or prove which account is authenticated.

## Load it in Chrome

1. Start the existing backend, normally at `http://127.0.0.1:8000`.
2. Open `chrome://extensions`.
3. Enable **Developer mode**.
4. Choose **Load unpacked** and select this `browser-extension` directory.
5. Open the extension popup and confirm the backend URL.

## Pair and give consent

1. Log in to the dashboard at `http://127.0.0.1:8000`.
2. Open `http://127.0.0.1:8000/docs`, expand `POST
   /browser-extension/pairing/start`, choose **Try it out**, then **Execute**.
   The login session authorizes the request. Copy the returned short-lived
   `pairing_code`.
3. Open the extension popup, paste the code, choose an installation label, and
   select **Pair extension**. The code is single-use and expires quickly.
4. Pairing alone does not enable collection. Review the popup's collection
   notice, then explicitly select **Enable monitoring**.
5. Visit a supported website in a tab. The extension sends sanitized metadata
   to `POST /browser-activity/events`.

The bearer token is stored in `chrome.storage.local` and is never put in a URL or logged. The dashboard session cookie is not used by event ingestion.

## Pause or disconnect

- **Pause monitoring** closes the current active-tab duration and stops
  collection/sending while retaining the pairing locally. Paused time is not
  included when monitoring resumes.
- **Disconnect** stops monitoring and clears the locally stored bearer token.
- **Revoke device** on the dashboard's **Monitoring** page revokes the
  server-side device. Disconnect alone does not revoke it. The equivalent
  authenticated endpoint is `POST /browser-extension/devices/{device_id}/revoke`.

If the code is expired/invalid, the device is revoked, or the backend is unavailable, the popup shows a status/error and the extension does not retry indefinitely.

## Permissions

The extension uses only `storage`, `tabs`, and `webNavigation`, plus host permissions for the six supported domains. It does not request `<all_urls>`, `cookies`, `history`, or `webRequest`.
