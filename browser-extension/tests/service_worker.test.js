import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const eventRequests = [];
const storage = {
  backendUrl: "http://127.0.0.1:8000",
  extensionToken: "test-extension-token",
  monitoringEnabled: true
};
const listeners = {
  committed: null,
  activated: null,
  removed: null,
  message: null
};
let activeTabUrl = "https://www.facebook.com/private/path?password=never-send";

globalThis.chrome = {
  storage: {
    local: {
      async get(defaults) {
        return { ...defaults, ...storage };
      },
      async set(values) {
        Object.assign(storage, values);
      },
      async remove(keys) {
        keys.forEach(key => delete storage[key]);
      }
    }
  },
  webNavigation: {
    onCommitted: {
      addListener(listener) {
        listeners.committed = listener;
      }
    }
  },
  tabs: {
    onActivated: {
      addListener(listener) {
        listeners.activated = listener;
      }
    },
    onRemoved: {
      addListener(listener) {
        listeners.removed = listener;
      }
    },
    async query() {
      return [{ id: 1, url: activeTabUrl }];
    }
  },
  runtime: {
    onMessage: {
      addListener(listener) {
        listeners.message = listener;
      }
    }
  }
};

globalThis.fetch = async (_url, options) => {
  eventRequests.push(JSON.parse(options.body));
  return { ok: true, status: 200 };
};

await import("../service_worker.js");
await new Promise(resolve => setImmediate(resolve));

function sendMessage(message) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Message timed out")), 1000);
    listeners.message(message, {}, response => {
      clearTimeout(timeout);
      resolve(response);
    });
  });
}

test("pause excludes paused time and payloads contain only consented metadata", async () => {
  const originalNow = Date.now;
  let now = 1000;
  Date.now = () => now;

  try {
    await listeners.committed({
      frameId: 0,
      tabId: 1,
      url: activeTabUrl,
      transitionType: "typed",
      timeStamp: 1
    });
    await listeners.activated({ tabId: 1 });

    now = 5000;
    assert.deepEqual(await sendMessage({ type: "setMonitoring", enabled: false }), {
      ok: true
    });
    const requestCountWhenPaused = eventRequests.length;

    now = 45000;
    activeTabUrl = "https://facebook.com/visited-while-paused?session_token=secret";
    await listeners.committed({
      frameId: 0,
      tabId: 1,
      url: activeTabUrl,
      transitionType: "typed",
      timeStamp: 2
    });
    assert.equal(eventRequests.length, requestCountWhenPaused);

    now = 50000;
    assert.deepEqual(await sendMessage({ type: "setMonitoring", enabled: true }), {
      ok: true
    });
    now = 51000;
    await listeners.activated({ tabId: 2 });

    const durations = eventRequests
      .filter(event => event.event_type === "duration_update")
      .map(event => event.duration_seconds);
    assert.deepEqual(durations, [4, 1]);
    assert.ok(eventRequests.every(event => {
      const serialized = JSON.stringify(event);
      return !/private\/path|visited-while-paused|password=|session_token=/.test(serialized);
    }));
    assert.ok(eventRequests.every(event =>
      Object.keys(event).sort().join(",") ===
      "consent_version,domain,event_type,idempotency_key,metadata,occurred_at" ||
      Object.keys(event).sort().join(",") ===
      "consent_version,domain,duration_seconds,event_type,idempotency_key,metadata,occurred_at"
    ));
  } finally {
    Date.now = originalNow;
  }
});

test("manifest grants no page-content, cookie, history, or request-inspection permissions", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("../manifest.json", import.meta.url), "utf8")
  );
  assert.deepEqual(manifest.permissions, ["storage", "tabs", "webNavigation"]);
  assert.equal("content_scripts" in manifest, false);
  assert.equal(manifest.host_permissions.includes("<all_urls>"), false);
  assert.equal(
    manifest.host_permissions.some(permission =>
      /cookies|history|webRequest/.test(permission)
    ),
    false
  );
});
