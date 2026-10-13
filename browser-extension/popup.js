import { normalizePairingCode } from "./domain_utils.js";

const $ = (id) => document.getElementById(id);

function send(message) {
  return chrome.runtime.sendMessage(message);
}

function showMessage(text, error = false) {
  $("message").textContent = text;
  $("message").className = error ? "notice error" : "notice";
}

async function refresh() {
  const state = await send({ type: "getStatus" });
  $("backend-url").value = state.backendUrl;
  $("status").textContent = `${state.paired ? "Paired" : "Not paired"} · ${state.status}`;
  $("toggle").disabled = !state.paired;
  $("toggle").textContent = state.monitoringEnabled ? "Pause monitoring" : "Enable monitoring";
}

$("save-url").addEventListener("click", async () => {
  try {
    const value = new URL($("backend-url").value.trim()).toString().replace(/\/+$/, "");
    if (!["http:", "https:"].includes(new URL(value).protocol)) throw new Error();
    await send({ type: "saveBackendUrl", backendUrl: value });
    showMessage("Backend URL saved.");
    await refresh();
  } catch {
    showMessage("Enter a valid http:// or https:// backend URL.", true);
  }
});

$("pair").addEventListener("click", async () => {
  const pairingCode = normalizePairingCode($("pairing-code").value);
  const installationLabel = $("installation-label").value.trim();
  if (!pairingCode || !installationLabel) {
    showMessage("Pairing code and installation label are required.", true);
    return;
  }
  const result = await send({ type: "pair", pairingCode, installationLabel });
  showMessage(result.ok ? "Paired. Monitoring remains paused until enabled." : result.error, !result.ok);
  await refresh();
});

$("toggle").addEventListener("click", async () => {
  const state = await send({ type: "getStatus" });
  await send({ type: "setMonitoring", enabled: !state.monitoringEnabled });
  showMessage(state.monitoringEnabled ? "Monitoring paused." : "Monitoring enabled.");
  await refresh();
});

$("disconnect").addEventListener("click", async () => {
  await send({ type: "disconnect" });
  showMessage("Disconnected. Revoke the server-side device separately if needed.");
  await refresh();
});

refresh().catch(() => showMessage("Unable to read extension status.", true));
