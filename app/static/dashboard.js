const $ = id => document.getElementById(id);

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.json()).detail || "Request failed");
  return response.status === 204 ? null : response.json();
}

function date(value) {
  return new Date(value).toLocaleString();
}

function clear(element) {
  element.replaceChildren();
}

function textCell(value) {
  const cell = document.createElement("td");
  cell.textContent = value == null ? "" : String(value);
  return cell;
}

function emptyRow(columnCount, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columnCount;
  cell.textContent = message;
  row.appendChild(cell);
  return row;
}

function listItem(message) {
  const item = document.createElement("li");
  item.textContent = message;
  return item;
}

function renderSessions(items) {
  const rows = $("rows");
  clear(rows);
  if (!items.length) {
    rows.appendChild(emptyRow(6, "No sessions found."));
    return;
  }
  items.forEach(session => {
    const row = document.createElement("tr");
    row.append(textCell(session.id));
    const status = textCell(session.status);
    status.className = session.status;
    row.append(status, textCell(date(session.created_at)), textCell(date(session.last_activity_at)), textCell(date(session.expires_at)));
    const actions = document.createElement("td");
    if (session.status === "active") {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Revoke";
      button.addEventListener("click", () => revoke(session.id));
      actions.appendChild(button);
    }
    row.appendChild(actions);
    rows.appendChild(row);
  });
}

function renderSessionInventory(items, stats) {
  $("inventory-total").textContent = stats.total;
  $("inventory-active").textContent = stats.by_status.active || 0;
  $("inventory-unknown").textContent = stats.by_status.unknown || 0;
  $("inventory-revoked").textContent = stats.by_status.revoked || 0;
  const rows = $("session-inventory-rows");
  clear(rows);
  if (!items.length) {
    $("session-inventory-status").textContent = "No session inventory records.";
    rows.appendChild(emptyRow(12, "No session inventory records found."));
    return;
  }
  $("session-inventory-status").textContent = `${items.length} session inventory record${items.length === 1 ? "" : "s"} loaded.`;
  items.forEach(record => {
    const row = document.createElement("tr");
    const status = textCell(record.status);
    status.className = record.status;
    const actions = document.createElement("td");
    if (record.status !== "revoked") {
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.textContent = "Refresh status";
      refresh.addEventListener("click", () => refreshInventory(record.id));
      const revokeButton = document.createElement("button");
      revokeButton.type = "button";
      revokeButton.textContent = "Revoke";
      revokeButton.addEventListener("click", () => revokeInventory(record.id));
      actions.append(refresh, revokeButton);
    } else {
      actions.textContent = "—";
    }
    row.append(
      textCell(record.id),
      textCell(record.user_id),
      textCell(record.platform),
      textCell(record.session_type),
      status,
      textCell(record.authentication_status),
      textCell(date(record.created_at)),
      textCell(record.last_observed_activity ? date(record.last_observed_activity) : "Not observed"),
      textCell(record.expires_at ? date(record.expires_at) : "Not configured"),
      textCell(date(record.last_status_check)),
      textCell(record.status_reason),
      actions
    );
    rows.appendChild(row);
  });
}

function renderSessionInventoryError(message) {
  $("session-inventory-status").textContent = message;
  clear($("session-inventory-rows"));
  $("session-inventory-rows").appendChild(emptyRow(12, "Session inventory could not be loaded."));
}

function renderEvents(items) {
  const events = $("events");
  clear(events);
  if (!items.length) {
    events.appendChild(listItem("No authorized session events yet."));
    return;
  }
  items.forEach(event => {
    events.appendChild(listItem(`Confirmed session event: ${event.event_type} session ${event.session_id} at ${date(event.created_at)}`));
  });
}

function renderBrowserActivity(items) {
  const rows = $("browser-activity-rows");
  const status = $("browser-activity-status");
  clear(rows);
  if (!items.length) {
    status.textContent = "No browser activity recorded.";
    rows.appendChild(emptyRow(5, "No browser activity found."));
    return;
  }
  status.textContent = `${items.length} browser activit${items.length === 1 ? "y" : "ies"} loaded.`;
  items.forEach(event => {
    const row = document.createElement("tr");
    row.append(
      textCell(event.domain),
      textCell(event.event_type),
      textCell(date(event.occurred_at)),
      textCell(event.duration_seconds == null ? "—" : `${event.duration_seconds} seconds`),
      textCell(event.source)
    );
    rows.appendChild(row);
  });
}

function renderBrowserActivityError(message) {
  const rows = $("browser-activity-rows");
  clear(rows);
  $("browser-activity-status").textContent = message;
  rows.appendChild(emptyRow(5, "Browser activity could not be loaded."));
}

function renderSocialBrowserActivity(items) {
  const rows = $("social-browser-activity-rows");
  const status = $("social-browser-activity-status");
  clear(rows);
  if (!items.length) {
    status.textContent = "No recent Facebook or Instagram browser activity recorded.";
    rows.appendChild(emptyRow(5, "No Facebook or Instagram activity found."));
    return;
  }
  status.textContent = `${items.length} Facebook/Instagram activit${items.length === 1 ? "y" : "ies"} loaded.`;
  items.forEach(event => {
    const row = document.createElement("tr");
    row.append(
      textCell(event.domain),
      textCell(event.event_type),
      textCell(date(event.occurred_at)),
      textCell(event.duration_seconds == null ? "—" : `${event.duration_seconds} seconds`),
      textCell(event.consent_version)
    );
    rows.appendChild(row);
  });
}

function renderSocialBrowserActivityError(message) {
  const rows = $("social-browser-activity-rows");
  clear(rows);
  $("social-browser-activity-status").textContent = message;
  rows.appendChild(emptyRow(5, "Facebook and Instagram activity could not be loaded."));
}

function renderSocialBrowserStatus(items, thresholdSeconds) {
  const rows = $("social-browser-status-rows");
  const message = $("social-browser-status-message");
  clear(rows);
  message.textContent = `Status is based on a ${Math.round(thresholdSeconds / 60)}-minute activity threshold.`;
  items.forEach(item => {
    const row = document.createElement("tr");
    const status = textCell(item.status.replace("_", " "));
    status.className = item.status;
    row.append(
      textCell(item.platform),
      status,
      textCell(item.last_activity_at ? date(item.last_activity_at) : "Not observed"),
      textCell(item.explanation)
    );
    rows.appendChild(row);
  });
}

function renderSocialBrowserStatusError(message) {
  const rows = $("social-browser-status-rows");
  clear(rows);
  $("social-browser-status-message").textContent = message;
  rows.appendChild(emptyRow(4, "Facebook and Instagram status could not be loaded."));
}

function deviceStatus(device) {
  if (device.revoked_at) return "revoked";
  if (device.expires_at && new Date(device.expires_at) <= new Date()) return "expired";
  return "active";
}

function renderBrowserExtensionStatus(devices, activity) {
  const rows = $("browser-extension-rows");
  const status = $("browser-extension-status");
  const consent = $("browser-extension-consent");
  const message = $("browser-extension-message");
  clear(rows);
  message.textContent = "";
  if (!devices.length) {
    status.textContent = "No browser extension devices are paired.";
    rows.appendChild(emptyRow(5, "No paired devices found."));
  } else {
    status.textContent = `${devices.length} paired device${devices.length === 1 ? "" : "s"}.`;
    devices.forEach(device => {
      const row = document.createElement("tr");
      const state = deviceStatus(device);
      const stateCell = textCell(state);
      stateCell.className = state;
      const actions = document.createElement("td");
      if (state === "active") {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Revoke device";
        button.addEventListener("click", () => revokeBrowserDevice(device.id));
        actions.appendChild(button);
      } else {
        actions.textContent = "—";
      }
      row.append(
        textCell(device.installation_label),
        stateCell,
        textCell(device.last_seen_at ? date(device.last_seen_at) : "Not seen yet"),
        textCell(device.expires_at ? date(device.expires_at) : "No expiry"),
        actions
      );
      rows.appendChild(row);
    });
  }
  const latest = activity[0];
  consent.textContent = latest
    ? `Consent version observed on latest event: ${latest.consent_version}. This does not confirm that monitoring is currently enabled or paused.`
    : "No browser activity event is available to report an observed consent version.";
}

function renderBrowserExtensionError(message) {
  clear($("browser-extension-rows"));
  $("browser-extension-status").textContent = message;
  $("browser-extension-consent").textContent = "";
  $("browser-extension-rows").appendChild(emptyRow(5, "Browser extension status could not be loaded."));
}

function renderProtocolOptions(protocols, selected) {
  const select = $("network-protocol");
  clear(select);
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All protocols";
  select.appendChild(all);
  protocols.forEach(protocol => {
    const option = document.createElement("option");
    option.value = protocol;
    option.textContent = protocol;
    select.appendChild(option);
  });
  select.value = selected;
}

function renderProtocols(protocolCounts) {
  const list = $("protocols");
  clear(list);
  const entries = Object.entries(protocolCounts);
  if (!entries.length) {
    list.appendChild(listItem("No imported network observations."));
    return;
  }
  entries.forEach(([protocol, count]) => list.appendChild(listItem(`${protocol}: ${count}`)));
}

function renderObservations(items) {
  const rows = $("observation-rows");
  clear(rows);
  if (!items.length) {
    rows.appendChild(emptyRow(5, "No observations match the filters."));
    return;
  }
  items.forEach(observation => {
    const row = document.createElement("tr");
    row.append(
      textCell(date(observation.observed_at)),
      textCell(observation.protocol),
      textCell(observation.observation_source),
      textCell(observation.destination || "redacted"),
      textCell(`${observation.packet_count || "-"} / ${observation.byte_count || "-"}`)
    );
    rows.appendChild(row);
  });
}

function renderConnections(items) {
  const list = $("connections");
  clear(list);
  if (!items.length) {
    list.appendChild(listItem("No authorized provider connections."));
    return;
  }
  items.forEach(connection => {
    let message = `${connection.provider} (${connection.connection_mode}): ${connection.external_account_id} — authorization ${connection.authorization_status}, health ${connection.health_status}`;
    if (connection.last_checked_at) message += ` (checked ${date(connection.last_checked_at)})`;
    if (connection.error_code) message += ` — ${connection.error_code}`;
    list.appendChild(listItem(message));
  });
}

function renderConsent(items) {
  const list = $("consent");
  clear(list);
  if (!items.length) {
    list.appendChild(listItem("No first-party consent records."));
    return;
  }
  items.forEach(event => {
    list.appendChild(listItem(`${event.website}: ${event.choice}, policy ${event.policy_version}, ${date(event.occurred_at)}`));
  });
}

async function load() {
  try {
    const stats = await api("/sessions/stats");
    ["total", "active", "expired", "revoked"].forEach(key => $(key).textContent = stats[key]);
    const status = $("status").value;
    const eventType = $("event-type").value;
    const protocol = $("network-protocol").value;
    const source = $("network-source").value;
    $("browser-activity-status").textContent = "Loading browser activity...";
    const [sessions, events, inventory, inventoryStats, browserActivity, browserStatus, devices, network, observations, connections, consent] = await Promise.all([
      api("/sessions?page_size=100" + (status ? "&status=" + encodeURIComponent(status) : "")),
      api("/sessions/events" + (eventType ? "?event_type=" + encodeURIComponent(eventType) : "")),
      api("/session-inventory"),
      api("/session-inventory/stats"),
      api("/browser-activity/events?limit=100"),
      api("/browser-activity/status"),
      api("/browser-extension/devices"),
      api("/monitoring/network/stats"),
      api("/monitoring/network?limit=100" + (protocol ? "&protocol=" + encodeURIComponent(protocol) : "") + (source ? "&source=" + encodeURIComponent(source) : "")),
      api("/monitoring/connections"),
      api("/monitoring/consent")
    ]);
    renderSessions(sessions.items);
    renderSessionInventory(inventory.items, inventoryStats);
    renderEvents(events.items);
    renderBrowserActivity(browserActivity);
    renderBrowserExtensionStatus(devices, browserActivity);
    renderSocialBrowserStatus(browserStatus.items, browserStatus.inactivity_threshold_seconds);
    $("social-browser-activity-status").textContent = "Loading Facebook and Instagram activity...";
    const socialResults = await Promise.allSettled([
      api("/browser-activity/events?domain=facebook.com&limit=100"),
      api("/browser-activity/events?domain=instagram.com&limit=100")
    ]);
    const failedSocialResult = socialResults.find(result => result.status === "rejected");
    if (failedSocialResult) {
      renderSocialBrowserActivityError("Unable to load Facebook and Instagram activity.");
      renderSocialBrowserStatusError("Unable to load Facebook and Instagram status.");
    } else {
      const socialActivity = socialResults
        .flatMap(result => result.value)
        .sort((left, right) => new Date(right.occurred_at) - new Date(left.occurred_at));
      renderSocialBrowserActivity(socialActivity);
    }
    $("observation-total").textContent = network.total;
    $("protocol-total").textContent = Object.keys(network.by_protocol).length;
    renderProtocolOptions(Object.keys(network.by_protocol), protocol);
    renderProtocols(network.by_protocol);
    $("observation-status").textContent = network.last_ingestion_at ? `Last ingestion: ${date(network.last_ingestion_at)} (metadata only)` : "No network export has been imported.";
    renderObservations(observations);
    renderConnections(connections);
    renderConsent(consent);
  } catch (error) {
    $("message").textContent = error.message;
    renderBrowserActivityError("Unable to load browser activity.");
    renderBrowserExtensionError("Unable to load browser extension status.");
    renderSessionInventoryError("Unable to load session inventory.");
    renderSocialBrowserActivityError("Unable to load Facebook and Instagram activity.");
  }
}

async function revoke(id) {
  try {
    await api(`/sessions/${id}/revoke`, {method: "POST"});
    await load();
  } catch (error) {
    $("message").textContent = error.message;
  }
}

async function revokeBrowserDevice(id) {
  if (!window.confirm("Revoke this browser extension device? It will no longer be able to submit events.")) return;
  const message = $("browser-extension-message");
  message.textContent = "Revoking device...";
  try {
    await api(`/browser-extension/devices/${id}/revoke`, {method: "POST"});
    message.textContent = "Device revoked.";
    await load();
  } catch (error) {
    message.textContent = `Could not revoke device: ${error.message}`;
  }
}

async function refreshInventory(id) {
  try {
    await api(`/session-inventory/${id}/refresh`, {method: "POST"});
    await load();
  } catch (error) {
    $("message").textContent = error.message;
  }
}

async function revokeInventory(id) {
  if (!window.confirm("Revoke this session inventory record?")) return;
  try {
    await api(`/session-inventory/${id}/revoke`, {method: "POST"});
    await load();
  } catch (error) {
    $("message").textContent = error.message;
  }
}

$("login-form").onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api("/auth/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(Object.fromEntries(form))
    });
    $("login").hidden = true;
    $("dashboard").hidden = false;
    await load();
  } catch (error) {
    $("login-error").textContent = error.message;
  }
};

$("logout").onclick = async () => {
  await api("/auth/logout", {method: "POST"});
  location.reload();
};
$("refresh").onclick = load;
$("status").onchange = load;
$("event-type").onchange = load;
$("network-protocol").onchange = load;
$("network-source").onchange = load;

api("/auth/me").then(() => {
  $("login").hidden = true;
  $("dashboard").hidden = false;
  load();
}).catch(error => {
  if (error.message === "Failed to fetch") $("startup-error").textContent = "Cannot reach the server. Start Uvicorn and reload this page.";
});
