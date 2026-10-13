export const SUPPORTED_DOMAINS = Object.freeze([
  "facebook.com",
  "instagram.com",
  "linkedin.com",
  "tiktok.com",
  "x.com",
  "youtube.com"
]);

export function normalizePairingCode(value) {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  if (!trimmed) return "";

  try {
    const parsed = JSON.parse(trimmed);
    if (typeof parsed === "string") return parsed.trim();
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof parsed.pairing_code === "string"
    ) {
      return parsed.pairing_code.trim();
    }
  } catch {
    // Treat non-JSON input as the raw pairing code.
  }
  return trimmed;
}

const FORBIDDEN_METADATA_KEYS = new Set([
  "access_token",
  "authorization",
  "body",
  "cookie",
  "cookies",
  "content",
  "password",
  "password_hash",
  "request_headers",
  "session_token"
]);

export function supportedDomainFromUrl(value) {
  if (typeof value !== "string") return null;

  let hostname;
  try {
    hostname = new URL(value).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return null;
  }

  for (const domain of SUPPORTED_DOMAINS) {
    if (hostname === domain || hostname.endsWith(`.${domain}`)) {
      return domain;
    }
  }
  return null;
}

export function sanitizeMetadata(metadata = {}) {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return {};
  }

  const result = {};
  for (const [key, value] of Object.entries(metadata)) {
    if (
      typeof key !== "string" ||
      FORBIDDEN_METADATA_KEYS.has(key.toLowerCase()) ||
      !/^[a-zA-Z0-9_.-]{1,64}$/.test(key)
    ) {
      continue;
    }
    if (
      value === null ||
      typeof value === "string" ||
      typeof value === "boolean" ||
      (typeof value === "number" && Number.isFinite(value))
    ) {
      result[key] = value;
    }
    if (Object.keys(result).length >= 20) break;
  }
  return result;
}

export function buildEventPayload({
  eventType,
  occurredAt = new Date().toISOString(),
  domain,
  durationSeconds,
  metadata,
  idempotencyKey = crypto.randomUUID()
}) {
  if (!SUPPORTED_DOMAINS.includes(domain)) {
    throw new Error("Unsupported domain");
  }
  const payload = {
    event_type: eventType,
    occurred_at: occurredAt,
    domain,
    metadata: sanitizeMetadata(metadata),
    consent_version: "v1",
    idempotency_key: idempotencyKey
  };
  if (durationSeconds !== undefined) {
    payload.duration_seconds = Math.max(0, Math.min(86400, Number(durationSeconds)));
  }
  return payload;
}
