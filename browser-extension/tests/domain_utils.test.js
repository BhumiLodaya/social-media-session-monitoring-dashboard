import test from "node:test";
import assert from "node:assert/strict";
import {
  buildEventPayload,
  normalizePairingCode,
  sanitizeMetadata,
  supportedDomainFromUrl
} from "../domain_utils.js";

test("accepts a raw pairing code or the copied pairing response", () => {
  assert.equal(normalizePairingCode("  abc123  "), "abc123");
  assert.equal(
    normalizePairingCode('{"pairing_code":"abc123","expires_at":"future"}'),
    "abc123"
  );
  assert.equal(normalizePairingCode('"abc123"'), "abc123");
});

test("normalizes only supported hostnames and never returns a URL", () => {
  assert.equal(supportedDomainFromUrl("https://www.instagram.com/path?q=1#fragment"), "instagram.com");
  assert.equal(supportedDomainFromUrl("https://m.youtube.com/watch?v=1"), "youtube.com");
  assert.equal(supportedDomainFromUrl("https://notfacebook.com/"), null);
  assert.equal(supportedDomainFromUrl("https://example.com/"), null);
  assert.equal(supportedDomainFromUrl("facebook.com"), null);
});

test("sanitizes metadata and drops sensitive or non-scalar values", () => {
  assert.deepEqual(
    sanitizeMetadata({
      transition: "link",
      tab_id: 7,
      cookies: "secret",
      request_headers: "secret",
      nested: { content: "secret" }
    }),
    { transition: "link", tab_id: 7 }
  );
});

test("builds a backend-compatible payload without URL data", () => {
  const payload = buildEventPayload({
    eventType: "navigation",
    domain: "facebook.com",
    metadata: { transition: "typed" },
    idempotencyKey: "test-event-1"
  });
  assert.deepEqual(payload, {
    event_type: "navigation",
    occurred_at: payload.occurred_at,
    domain: "facebook.com",
    metadata: { transition: "typed" },
    consent_version: "v1",
    idempotency_key: "test-event-1"
  });
  assert.equal("url" in payload, false);
});
