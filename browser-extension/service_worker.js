import {
  buildEventPayload,
  supportedDomainFromUrl
} from "./domain_utils.js";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 8000;
const TAB_STATE_PREFIX = "tabState:";

let tabStates = new Map();
let activeTabId = null;
let status = "disabled";

async function getSettings() {
  return chrome.storage.local.get({
    backendUrl: DEFAULT_BACKEND_URL,
    extensionToken: "",
    monitoringEnabled: false
  });
}

function backendUrl(value) {
  return value.replace(/\/+$/, "");
}

async function setStatus(value) {
  status = value;
  await chrome.storage.local.set({ connectionStatus: value });
}

async function sendEvent(payload) {
  const settings = await getSettings();
  if (!settings.monitoringEnabled || !settings.extensionToken) {
    return false;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(
      `${backendUrl(settings.backendUrl)}/browser-activity/events`,
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${settings.extensionToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload),
        signal: controller.signal
      }
    );
    if (response.ok) {
      await setStatus("connected");
      return true;
    }
    if (response.status === 401) {
      await setStatus("authorization-required");
    } else {
      await setStatus(`backend-error-${response.status}`);
    }
    return false;
  } catch {
    await setStatus("offline");
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function recordNavigation(tabId, url, transitionType = "link", navigationTimestamp = null) {
  const domain = supportedDomainFromUrl(url);
  if (!domain) {
    if (tabId === activeTabId) await finishActiveTab();
    tabStates.delete(tabId);
    return;
  }

  const previous = tabStates.get(tabId);
  if (
    previous &&
    navigationTimestamp !== null &&
    previous.lastNavigationTimestamp === navigationTimestamp
  ) {
    return;
  }
  tabStates.set(tabId, {
    domain,
    lastActivatedAt: previous?.lastActivatedAt ?? null,
    lastNavigationTimestamp: navigationTimestamp
  });

  const payload = buildEventPayload({
    eventType: "navigation",
    domain,
    metadata: { transition: transitionType }
  });
  await sendEvent(payload);
}

async function finishActiveTab() {
  if (activeTabId === null) return;
  const state = tabStates.get(activeTabId);
  if (!state || state.lastActivatedAt === null) return;

  const duration = Math.floor((Date.now() - state.lastActivatedAt) / 1000);
  await sendEvent(buildEventPayload({
    eventType: "duration_update",
    domain: state.domain,
    durationSeconds: duration,
    metadata: { tab_id: activeTabId }
  }));
  await sendEvent(buildEventPayload({
    eventType: "tab_deactivated",
    domain: state.domain,
    metadata: { tab_id: activeTabId }
  }));
  state.lastActivatedAt = null;
}

async function activateTab(tabId) {
  await finishActiveTab();
  activeTabId = tabId;
  const state = tabStates.get(tabId);
  if (!state) return;
  state.lastActivatedAt = Date.now();
  await sendEvent(buildEventPayload({
    eventType: "tab_activated",
    domain: state.domain,
    metadata: { tab_id: tabId }
  }));
}

async function refreshMonitoringState() {
  const settings = await getSettings();
  if (!settings.monitoringEnabled || !settings.extensionToken) {
    await setStatus("disabled");
  } else if (status === "disabled") {
    await setStatus("ready");
  }
}

chrome.webNavigation.onCommitted.addListener(async (details) => {
  if (details.frameId !== 0) return;
  const settings = await getSettings();
  if (!settings.monitoringEnabled || !settings.extensionToken) return;
  await recordNavigation(
    details.tabId,
    details.url,
    details.transitionType,
    details.timeStamp ?? null
  );
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const settings = await getSettings();
  if (!settings.monitoringEnabled || !settings.extensionToken) return;
  await activateTab(tabId);
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (tabId === activeTabId) {
    await finishActiveTab();
    activeTabId = null;
  }
  tabStates.delete(tabId);
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message.type === "getStatus") {
      const settings = await getSettings();
      sendResponse({
        backendUrl: settings.backendUrl,
        monitoringEnabled: settings.monitoringEnabled,
        paired: Boolean(settings.extensionToken),
        status
      });
      return;
    }
    if (message.type === "setMonitoring") {
      await chrome.storage.local.set({ monitoringEnabled: Boolean(message.enabled) });
      await refreshMonitoringState();
      sendResponse({ ok: true });
      return;
    }
    if (message.type === "saveBackendUrl") {
      await chrome.storage.local.set({ backendUrl: message.backendUrl });
      sendResponse({ ok: true });
      return;
    }
    if (message.type === "pair") {
      const settings = await getSettings();
      const response = await fetch(
        `${backendUrl(settings.backendUrl)}/browser-extension/pairing/exchange`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            pairing_code: message.pairingCode,
            installation_label: message.installationLabel
          })
        }
      );
      if (!response.ok) {
        sendResponse({ ok: false, error: response.status === 401 ? "Invalid or expired pairing code." : `Backend returned ${response.status}.` });
        return;
      }
      const data = await response.json();
      await chrome.storage.local.set({
        extensionToken: data.extension_token,
        monitoringEnabled: false,
        connectionStatus: "paired"
      });
      await refreshMonitoringState();
      sendResponse({ ok: true });
      return;
    }
    if (message.type === "disconnect") {
      await finishActiveTab();
      tabStates.clear();
      activeTabId = null;
      await chrome.storage.local.remove(["extensionToken", "monitoringEnabled", "connectionStatus"]);
      await setStatus("disconnected");
      sendResponse({ ok: true });
    }
  })().catch(async () => {
    await setStatus("offline");
    sendResponse({ ok: false, error: "Unable to reach the backend." });
  });
  return true;
});

refreshMonitoringState();
