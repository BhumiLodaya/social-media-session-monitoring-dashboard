const $ = id => document.getElementById(id);

const ROUTES = {
  "/": "overview",
  "/user-directory": "users",
  "/login-activity": "login-activity",
  "/dashboard-sessions": "sessions",
  "/monitoring": "monitoring",
  "/panels": "panels",
  "/connected-accounts": "connected-accounts",
  "/organic-ids": "organic-ids",
  "/diagnosis": "diagnosis",
};

const PANEL_LABELS = {
  overview: "Overview",
  users: "Users",
  "user-detail": "User detail",
  "login-activity": "Login Activity",
  sessions: "Sessions",
  monitoring: "Monitoring",
  panels: "Panel Usage",
  "connected-accounts": "Connected Accounts",
  "organic-ids": "Organic IDs",
  diagnosis: "Post Reach Diagnosis",
};

let cachedUsers = [];
let usersPage = 1;
const usersPageSize = 20;
let currentUser = null;

function parseRoute() {
  const match = location.pathname.match(/^\/users\/(\d+)$/);
  if (match) return {view: "user-detail", userId: Number(match[1])};
  return {view: ROUTES[location.pathname] || "overview"};
}

async function api(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json();
    const detail = body.detail;
    const message = Array.isArray(detail)
      ? detail.map(item => item.msg).join("; ")
      : detail;
    throw new Error(message || "Request failed");
  }
  return response.status === 204 ? null : response.json();
}

function date(value) {
  if (!value) return "Not recorded";
  const timestamp = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  return new Date(timestamp).toLocaleString();
}

function clear(element) {
  element.replaceChildren();
}

function textCell(value) {
  const cell = document.createElement("td");
  cell.textContent = value == null ? "" : String(value);
  return cell;
}

function activityMetadata(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "—";
  return ["transition", "tab_id"]
    .filter(key => value[key] !== undefined && value[key] !== null)
    .map(key => `${key}: ${String(value[key])}`)
    .join(", ") || "—";
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
    rows.appendChild(emptyRow(7, "No browser activity found."));
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
      textCell(currentUser?.username || "Current user"),
      textCell(activityMetadata(event.metadata)),
      textCell(event.source)
    );
    rows.appendChild(row);
  });
}

function renderBrowserActivityError(message) {
  const rows = $("browser-activity-rows");
  clear(rows);
  $("browser-activity-status").textContent = message;
  rows.appendChild(emptyRow(7, "Browser activity could not be loaded."));
}

function renderSocialBrowserActivity(items) {
  const rows = $("social-browser-activity-rows");
  const status = $("social-browser-activity-status");
  clear(rows);
  if (!items.length) {
    status.textContent = "No recent Facebook or Instagram browser activity recorded.";
    rows.appendChild(emptyRow(7, "No Facebook or Instagram activity found."));
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
      textCell(currentUser?.username || "Current user"),
      textCell(activityMetadata(event.metadata)),
      textCell(event.consent_version)
    );
    rows.appendChild(row);
  });
}

function renderSocialBrowserActivityError(message) {
  const rows = $("social-browser-activity-rows");
  clear(rows);
  $("social-browser-activity-status").textContent = message;
  rows.appendChild(emptyRow(7, "Facebook and Instagram activity could not be loaded."));
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
    const item = listItem("");
    if (connection.connection_mode === "demo") item.appendChild(badge("Demo data"));
    item.appendChild(document.createTextNode(message));
    list.appendChild(item);
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

function badge(label) {
  const element = document.createElement("span");
  element.className = "badge";
  element.textContent = label;
  return element;
}

function renderSocialConnections(items) {
  const list = $("social-connections");
  clear(list);
  if (!items.length) {
    list.appendChild(listItem("No connected accounts yet — start the demo or connect an account."));
    return;
  }
  items.forEach(connection => {
    const item = listItem("");
    if (connection.connection_mode === "demo") item.appendChild(badge("Demo data"));
    item.appendChild(document.createTextNode(`${connection.provider} (${connection.connection_mode}) — ${connection.authorization_status}, health ${connection.health_status} `));
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Disconnect";
    button.addEventListener("click", async () => {
      try {
        await api(`/social/connections/${connection.id}`, {method: "DELETE"});
        await loadSocial();
      } catch (error) {
        $("social-accounts-status").textContent = `Could not disconnect: ${error.message}`;
      }
    });
    item.appendChild(button);
    list.appendChild(item);
  });
}

function renderParticipants(items) {
  const list = $("participants");
  clear(list);
  if (!items.length) {
    list.appendChild(listItem("No participants yet — create an invitation to get started."));
    return;
  }
  items.forEach(item => {
    const row = listItem("");
    if (item.is_demo) row.appendChild(badge("Demo data"));
    row.appendChild(document.createTextNode(`${item.display_name} — consent ${item.consent_status}, participation ${item.participation_status}`));
    list.appendChild(row);
  });
}

function drawDiagnosisChart(currentReach, baselineReach) {
  const canvas = $("diagnosis-chart");
  if (!canvas) return;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  if (currentReach == null || baselineReach == null) {
    context.fillStyle = "#657386";
    context.font = "14px sans-serif";
    context.fillText("Chart unavailable until baseline and latest reach are known.", 16, 32);
    return;
  }
  const max = Math.max(currentReach, baselineReach, 1);
  const barWidth = 120;
  const baseY = canvas.height - 40;
  const scale = (baseY - 30) / max;
  context.fillStyle = "#1f5f9f";
  context.fillRect(80, baseY - baselineReach * scale, barWidth, baselineReach * scale);
  context.fillStyle = "#147a4b";
  context.fillRect(280, baseY - currentReach * scale, barWidth, currentReach * scale);
  context.fillStyle = "#172536";
  context.font = "13px sans-serif";
  context.fillText("Baseline median", 80, baseY + 18);
  context.fillText("Latest post", 280, baseY + 18);
  context.fillText(String(baselineReach), 80, baseY - baselineReach * scale - 8);
  context.fillText(String(currentReach), 280, baseY - currentReach * scale - 8);
}

function renderDiagnosis(data) {
  const isDemo = data.source === "synthetic_demo";
  const summary = $("diagnosis-summary");
  $("diagnosis-status").replaceChildren();
  if (isDemo) $("diagnosis-status").appendChild(badge("Demo data"));
  $("diagnosis-status").appendChild(document.createTextNode(`${data.trend} trend (${data.source}). ${data.metric_notes.join(" ")}`));
  const hasNumber = value => typeof value === "number" && Number.isFinite(value);
  const comparableCount = data.baseline_comparable_count;
  const latest = data.posts.length
    ? [...data.posts].sort((left, right) => new Date(right.published_at) - new Date(left.published_at))[0]
    : null;
  const statusLabel = data.status || "Insufficient data";
  $("diagnosis-result-status").textContent = statusLabel;
  $("diagnosis-result-status").className = statusLabel.includes("Above") ? "active"
    : statusLabel.includes("Below") ? "expired" : "muted";
  $("diagnosis-reach").textContent = latest?.reach ?? "Unavailable";
  $("diagnosis-impressions").textContent = latest?.impressions ?? "Unavailable";
  if (latest?.engagement_rate == null) {
    $("diagnosis-engagement").textContent = "Unavailable";
  } else {
    const denominator = latest.reach ?? latest.impressions;
    $("diagnosis-engagement").textContent = `${latest.engagement_rate}% (of ${denominator ?? "unknown"})`;
  }
  $("diagnosis-baseline-reach").textContent = hasNumber(data.baseline_median_reach)
    ? data.baseline_median_reach.toLocaleString() : "Unavailable";
  $("diagnosis-reach-diff").textContent = hasNumber(data.baseline_difference_reach)
    ? data.baseline_difference_reach.toLocaleString() : "Unavailable";
  $("diagnosis-pct-diff").textContent = hasNumber(data.baseline_difference_percentage)
    ? `${data.baseline_difference_percentage}%` : "Unavailable";
  $("diagnosis-comparable").textContent = hasNumber(comparableCount) ? String(comparableCount) : "Unavailable";
  summary.hidden = !data.posts.length;
  const baseline = $("diagnosis-baseline");
  if (
    hasNumber(data.baseline_median_reach) &&
    hasNumber(data.baseline_difference_reach) &&
    hasNumber(data.baseline_difference_percentage) &&
    hasNumber(comparableCount) &&
    comparableCount >= 2 &&
    data.status
  ) {
    baseline.textContent =
      `Historical median reach ${data.baseline_median_reach.toLocaleString()} from ${comparableCount} comparable posts. ` +
      `Latest post is ${data.status.toLowerCase()} (${data.baseline_difference_reach.toLocaleString()} reach, ${data.baseline_difference_percentage}%).`;
  } else {
    baseline.textContent = "Insufficient historical reach data for a reliable baseline (need comparable posts with reach).";
  }
  drawDiagnosisChart(latest?.reach ?? null, data.baseline_median_reach ?? null);
  $("diagnosis-findings").textContent = data.findings.join(" ");
  const recommendations = $("diagnosis-recommendations");
  clear(recommendations);
  data.recommendations.forEach(item => {
    const row = listItem("");
    if (isDemo) row.appendChild(badge("Demo data"));
    row.appendChild(document.createTextNode(item));
    recommendations.appendChild(row);
  });
  const rows = $("diagnosis-rows");
  clear(rows);
  if (!data.posts.length) {
    rows.appendChild(emptyRow(9, "No analytics available yet — start the demo to load synthetic metrics."));
    return;
  }
  data.posts.forEach(post => {
    const row = document.createElement("tr");
    const title = textCell("");
    if (post.source === "demo") title.appendChild(badge("Demo data"));
    title.appendChild(document.createTextNode(post.title));
    row.append(
      title,
      textCell(post.likes),
      textCell(post.comments),
      textCell(post.shares ?? "—"),
      textCell(post.saves ?? "—"),
      textCell(post.reach ?? "Unavailable"),
      textCell(post.impressions ?? "Unavailable"),
      textCell(post.engagement_rate == null ? "Unavailable" : `${post.engagement_rate}%`),
      textCell(post.source)
    );
    rows.appendChild(row);
  });
}

async function loadSocial() {
  const [connections, participants] = await Promise.all([
    api("/social/connections"), api("/social/participants")
  ]);
  renderSocialConnections(connections);
  renderParticipants(participants);
  $("social-accounts-status").textContent = connections.length
    ? `${connections.length} connected account${connections.length === 1 ? "" : "s"}.`
    : "No connected accounts yet.";
  if (!connections.length) {
    renderNoDiagnosis("No analytics available yet — start the demo to load synthetic metrics.");
    return;
  }
  try {
    renderDiagnosis(await api("/social/analytics/diagnosis"));
  } catch (error) {
    renderNoDiagnosis(error.message.includes("Connect an account")
      ? "No analytics available yet — start the demo to load synthetic metrics."
      : `Diagnosis unavailable: ${error.message}`);
  }

}

function renderNoDiagnosis(message) {
  $("diagnosis-summary").hidden = true;
  $("diagnosis-status").textContent = message;
  clear($("diagnosis-rows"));
  $("diagnosis-rows").appendChild(emptyRow(9, message));
}

async function loadDiagnosisOnly() {
  try {
    const connections = await api("/social/connections");
    if (!connections.length) {
      renderNoDiagnosis("No analytics available yet — start the demo to load synthetic metrics.");
      return;
    }
    renderDiagnosis(await api("/social/analytics/diagnosis"));
  } catch (error) {
    renderNoDiagnosis(error.message.includes("Connect an account")
      ? "No analytics available yet — start the demo to load synthetic metrics."
      : `Diagnosis unavailable: ${error.message}`);
  }
}

function renderActivityTimeline(items) {
  const list = $("activity-timeline");
  clear(list);
  if (!items.length) {
    $("activity-timeline-status").textContent = "No activity recorded yet.";
    list.appendChild(listItem("Sign in and open dashboard sections to build a timeline."));
    return;
  }
  $("activity-timeline-status").textContent = `${items.length} recent event${items.length === 1 ? "" : "s"}.`;
  items.forEach(item => {
    const label = item.event_type === "panel_opened"
      ? `Opened ${PANEL_LABELS[item.device_label] || item.device_label}`
      : `${item.event_type} (${item.platform})`;
    list.appendChild(listItem(`${date(item.occurred_at)} — ${label} — ${item.account_label}`));
  });
}

async function loadActivityTimeline() {
  try {
    const result = await api("/login-activity/events?page_size=15");
    renderActivityTimeline(result.items);
  } catch (error) {
    $("activity-timeline-status").textContent = `Activity timeline unavailable: ${error.message}`;
    clear($("activity-timeline"));
  }
}

function renderUsersList(users, filter) {
  const rows = $("users-rows");
  clear(rows);
  const query = (filter || "").trim().toLowerCase();
  const filtered = query
    ? users.filter(user => user.username.toLowerCase().includes(query) || user.email?.toLowerCase().includes(query))
    : users;
  if (!filtered.length) {
    rows.appendChild(emptyRow(9, query ? "No account matches this search." : "No account found."));
    return;
  }
  filtered.forEach(user => {
    const row = document.createElement("tr");
    const actions = document.createElement("td");
    const link = document.createElement("a");
    link.href = `/users/${user.id}`;
    link.dataset.nav = "user-detail";
    link.dataset.userId = String(user.id);
    link.textContent = "View";
    actions.appendChild(link);
    const accountStatus = textCell(user.is_active ? "Active" : "Inactive");
    accountStatus.className = user.is_active ? "active" : "inactive";
    const role = textCell(user.role);
    const username = textCell("");
    if (user.is_demo) username.appendChild(badge("Synthetic demo"));
    username.appendChild(document.createTextNode(user.username));
    if (currentUser?.role === "admin" && user.id !== currentUser.id) {
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = user.is_active ? "button-danger" : "button-secondary";
      toggle.textContent = user.is_active ? "Deactivate" : "Activate";
      toggle.addEventListener("click", () => setAccountActive(user.id, !user.is_active));
      actions.append(" ", toggle);
    }
    row.append(
      username, textCell(user.email || "Not recorded"), role,
      textCell(date(user.created_at)), textCell(date(user.last_login_at)),
      textCell(date(user.last_logout_at)), accountStatus, textCell(user.session_status), actions
    );
    rows.appendChild(row);
  });
}

async function loadUsers() {
  $("users-title").textContent = currentUser?.role === "admin" ? "User administration" : "Your account";
  $("users-description").textContent = currentUser?.role === "admin"
    ? "Administrator view: all accounts, account timestamps, and current session status."
    : "Your account details. Account status and current session status are shown separately.";
  $("user-search-label").hidden = currentUser?.role !== "admin";
  $("users-status").textContent = "Loading users...";
  try {
    const query = new URLSearchParams({
      page: String(usersPage), page_size: String(usersPageSize)
    });
    const search = $("user-search").value.trim();
    if (search) query.set("search", search);
    const result = await api(`/users?${query}`);
    cachedUsers = result.items;
    renderUsersList(cachedUsers, search);
    const pages = Math.max(1, Math.ceil(result.total / result.page_size));
    $("users-page-status").textContent = `Page ${result.page} of ${pages} (${result.total} account${result.total === 1 ? "" : "s"})`;
    $("users-previous").disabled = result.page <= 1;
    $("users-next").disabled = result.page >= pages;
    $("users-status").textContent = result.total
      ? "Account details loaded."
      : "No account matches this search.";
  } catch (error) {
    $("users-status").textContent = `Could not load users: ${error.message}`;
    clear($("users-rows"));
    $("users-rows").appendChild(emptyRow(9, "User directory unavailable."));
  }
}

async function loadUserDetail(userId) {
  $("user-detail-status").textContent = "Loading user...";
  const fields = $("user-detail-fields");
  clear(fields);
  const statusToggle = $("user-account-toggle");
  statusToggle.hidden = true;
  try {
    const user = await api(`/users/${userId}/details`);
    $("user-detail-title").textContent = user.username;
    $("user-detail-status").textContent = "";
    const entries = [
      ["User ID", String(user.id)],
      ["Username", user.username],
      ["Account type", user.is_demo ? "Synthetic demo account" : "Application account"],
      ["Email", user.email || "Not recorded"],
      ["Role", user.role],
      ["Account created", date(user.created_at)],
      ["Account status", user.is_active ? "Active" : "Inactive"],
      ["Current session status", user.session_status],
      ["Dashboard sessions", String(user.session_count)],
      ["Active sessions", String(user.active_session_count)],
      ["Last successful login", date(user.last_login_at)],
      ["Last logout", date(user.last_logout_at)],
    ];
    entries.forEach(([label, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      fields.append(dt, dd);
    });
    if (currentUser?.role === "admin" && user.id !== currentUser.id) {
      statusToggle.hidden = false;
      statusToggle.className = user.is_active ? "button-danger" : "button-secondary";
      statusToggle.textContent = user.is_active ? "Deactivate account" : "Activate account";
      statusToggle.onclick = () => setAccountActive(user.id, !user.is_active);
    }
    const activityRows = $("user-activity-rows");
    clear(activityRows);
    if (!user.recent_activity.length) {
      activityRows.appendChild(emptyRow(4, "No account activity has been recorded."));
      $("user-activity-status").textContent = "No activity recorded.";
      return;
    }
    user.recent_activity.forEach(item => {
      const row = document.createElement("tr");
      row.append(
        textCell(date(item.occurred_at)), textCell(item.label || item.event_type),
        textCell(item.source), textCell(item.status)
      );
      row.children[1].textContent = item.event_type;
      activityRows.appendChild(row);
    });
    $("user-activity-status").textContent = `${user.recent_activity.length} recent event${user.recent_activity.length === 1 ? "" : "s"}.`;
  } catch (error) {
    $("user-detail-status").textContent = error.message;
    $("user-activity-status").textContent = "Account activity could not be loaded.";
  }
}

async function setAccountActive(userId, isActive) {
  const action = isActive ? "activate" : "deactivate";
  if (!window.confirm(`Are you sure you want to ${action} this account?`)) return;
  try {
    await api(`/users/${userId}/status`, {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({is_active: isActive}),
    });
    await loadUsers();
    if (parseRoute().view === "user-detail") {
      await loadUserDetail(userId);
      $("user-detail-status").textContent = `Account ${isActive ? "activated" : "deactivated"} successfully.`;
    } else {
      $("users-status").textContent = `Account ${isActive ? "activated" : "deactivated"} successfully.`;
    }
  } catch (error) {
    $("users-status").textContent = `Could not ${action} account: ${error.message}`;
    if (parseRoute().view === "user-detail") $("user-detail-status").textContent = error.message;
  }
}

function renderPanelUsage(items) {
  const rows = $("panel-usage-rows");
  clear(rows);
  if (!items.length) {
    rows.appendChild(emptyRow(3, "No panel usage recorded yet — open a sidebar section while signed in."));
    return;
  }
  items.forEach(item => {
    const row = document.createElement("tr");
    row.append(
      textCell(date(item.occurred_at)),
      textCell(PANEL_LABELS[item.panel_id] || item.panel_id),
      textCell(item.username)
    );
    rows.appendChild(row);
  });
}

async function loadPanelUsage() {
  $("panel-usage-status").textContent = "Loading panel usage...";
  try {
    const result = await api("/login-activity/panels?page_size=100");
    renderPanelUsage(result.items);
    $("panel-usage-status").textContent = `${result.total} panel event${result.total === 1 ? "" : "s"} recorded.`;
  } catch (error) {
    $("panel-usage-status").textContent = `Panel usage unavailable: ${error.message}`;
    clear($("panel-usage-rows"));
    $("panel-usage-rows").appendChild(emptyRow(3, "Could not load panel usage."));
  }
}

async function recordPanelOpen(panelId) {
  if (!panelId || $("dashboard").hidden) return;
  try {
    await api("/login-activity/panels", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({panel_id: panelId}),
    });
  } catch {
    /* ignore telemetry failures */
  }
}

function setActiveNav(view) {
  document.querySelectorAll(".sidebar-nav a[data-nav]").forEach(link => {
    link.classList.toggle("active", link.dataset.nav === view && view !== "user-detail");
  });
}

function showView(view, userId) {
  document.querySelectorAll(".view[data-view]").forEach(section => {
    section.hidden = section.dataset.view !== view;
  });
  setActiveNav(view === "user-detail" ? "users" : view);
  if (view === "users") loadUsers();
  if (view === "user-detail" && userId) loadUserDetail(userId);
  if (view === "login-activity") loadLoginActivity();
  if (view === "panels") loadPanelUsage();
  if (view === "diagnosis") loadDiagnosisOnly();
  if (view === "overview") loadActivityTimeline();
  const panelId = view === "user-detail" ? "user-detail" : view;
  recordPanelOpen(panelId);
}

function navigateTo(path, {replace = false} = {}) {
  if (replace) history.replaceState({}, "", path);
  else history.pushState({}, "", path);
  const route = parseRoute();
  showView(route.view, route.userId);
}

function bindNavigation() {
  document.addEventListener("click", event => {
    const link = event.target instanceof Element ? event.target.closest("a[data-nav]") : null;
    if (!link) return;
    const href = link.getAttribute("href");
    if (!href || !href.startsWith("/") || href === "/demo") return;
    event.preventDefault();
    document.querySelector(".sidebar")?.classList.remove("open");
    if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", "false");
    if (link.dataset.userId) navigateTo(`/users/${link.dataset.userId}`);
    else navigateTo(href);
  });
  window.addEventListener("popstate", () => {
    const route = parseRoute();
    showView(route.view, route.userId);
  });
}

function renderLoginActivity(items) {
    const rows = $("login-activity-rows");
    clear(rows);
    const platforms = new Set();
    const eventTypes = new Set();
    items.forEach(item => {
      platforms.add(item.platform);
      eventTypes.add(item.event_type);
      const row = document.createElement("tr");
      const account = textCell("");
      if (item.is_demo) account.appendChild(badge("Demo data"));
      account.appendChild(document.createTextNode(item.account_label));
      const status = textCell(`${item.status} / ${item.confidence}`);
      status.className = item.status;
      row.append(
        textCell(date(item.occurred_at)), account, textCell(item.platform),
        textCell(item.event_type), textCell(item.source), status,
        textCell(item.device_label || "Not available"),
        textCell(activityMetadata(item.metadata))
      );
      rows.appendChild(row);
    });
    if (!items.length) rows.appendChild(emptyRow(8, "No login or observed activity matches these filters."));
    const platformSelect = $("login-platform");
    const eventSelect = $("login-event-type");
    const selectedPlatform = platformSelect.value;
    const selectedEvent = eventSelect.value;
    [platformSelect, eventSelect].forEach(select => {
      const values = select === platformSelect ? platforms : eventTypes;
      const label = select === platformSelect ? "All platforms" : "All event types";
      clear(select);
      const all = document.createElement("option");
      all.value = "";
      all.textContent = label;
      select.appendChild(all);
      [...values].sort().forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      });
    });
    platformSelect.value = selectedPlatform;
    eventSelect.value = selectedEvent;
  }

async function loadLoginActivity() {
    const status = $("login-activity-status");
    status.textContent = "Loading login activity...";
    try {
      const platform = $("login-platform").value;
      const eventType = $("login-event-type").value;
      const activityStatus = $("login-status").value;
      const query = new URLSearchParams({page_size: "100"});
      if (platform) query.set("platform", platform);
      if (eventType) query.set("event_type", eventType);
      if (activityStatus) query.set("status", activityStatus);
      const [result, stats] = await Promise.all([
        api(`/login-activity/events?${query}`), api("/login-activity/stats")
      ]);
      renderLoginActivity(result.items);
      $("login-observed").textContent = stats.recent_observed_events;
      $("login-successful").textContent = stats.successful_dashboard_logins;
      $("login-failed").textContent = stats.failed_dashboard_logins;
      $("login-connected").textContent = stats.connected_social_accounts;
      $("login-reconnect").textContent = stats.accounts_requiring_reconnection;
      status.textContent = `${result.total} activity event${result.total === 1 ? "" : "s"} loaded.`;
    } catch (error) {
      status.textContent = `Login activity could not be loaded: ${error.message}`;
      clear($("login-activity-rows"));
      $("login-activity-rows").appendChild(emptyRow(8, "Login activity is unavailable. Retry after checking the server."));
  }
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
    await loadSocial();
    await loadLoginActivity();
    await loadActivityTimeline();
    const route = parseRoute();
    showView(route.view, route.userId);
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

bindNavigation();

const sidebarToggle = $("sidebar-toggle");
const sidebar = document.querySelector(".sidebar");
if (sidebarToggle && sidebar) {
  sidebarToggle.addEventListener("click", () => {
    const open = sidebar.classList.toggle("open");
    sidebarToggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
}

$("login-form").onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const user = await api("/auth/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(Object.fromEntries(form))
    });
    currentUser = user;
    $("login").hidden = true;
    $("dashboard").hidden = false;
    $("current-user").textContent = `Signed in as ${user.username}`;
    navigateTo("/", {replace: true});
    await load();
  } catch (error) {
    $("login-error").textContent = error.message;
  }
};

function renderAuthMode() {
  const registration = location.pathname === "/register";
  $("auth-title").textContent = registration ? "Create your account" : "Sign in";
  $("login-form").hidden = registration;
  $("registration-form").hidden = !registration;
}

$("registration-form").onsubmit = async event => {
  event.preventDefault();
  $("registration-error").textContent = "";
  $("registration-success").textContent = "";
  const values = Object.fromEntries(new FormData(event.target));
  try {
    const user = await api("/auth/register", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(values)
    });
    $("login-form").elements.username.value = user.username;
    $("login-form").elements.password.value = "";
    history.replaceState({}, "", "/login");
    renderAuthMode();
    $("registration-success").textContent = "Account created. Sign in with your new credentials.";
  } catch (error) {
    $("registration-error").textContent = error.message;
  }
};

if (location.pathname === "/register" || location.pathname === "/login") {
  renderAuthMode();
}

const logoutButton = $("logout");
if (logoutButton) {
  logoutButton.onclick = async () => {
    await api("/auth/logout", {method: "POST"});
    location.href = "/";
  };
}

if ($("user-search")) {
  $("user-search").addEventListener("input", () => {
    usersPage = 1;
    loadUsers();
  });
}
$("users-previous").onclick = () => { usersPage = Math.max(1, usersPage - 1); loadUsers(); };
$("users-next").onclick = () => { usersPage += 1; loadUsers(); };
$("refresh").onclick = load;
$("status").onchange = load;
$("event-type").onchange = load;
$("network-protocol").onchange = load;
$("network-source").onchange = load;
$("login-platform").onchange = loadLoginActivity;
$("login-event-type").onchange = loadLoginActivity;
$("login-status").onchange = loadLoginActivity;
$("start-meta-oauth").onclick = async () => {
  try {
    const result = await api("/social/oauth/meta/start");
    if (result.mode === "demo") {
      const callback = await api(`/social/oauth/callback?state=${encodeURIComponent(result.state)}&code=demo`);
      $("social-accounts-status").textContent = callback.message;
      await loadSocial();
    } else {
      location.href = result.authorization_url;
    }
  } catch (error) {
    $("social-accounts-status").textContent = error.message;
  }
};
$("create-demo-analytics").onclick = async () => {
  try {
    await api("/social/analytics/demo", {method: "POST"});
    await loadSocial();
  } catch (error) {
    $("diagnosis-status").textContent = error.message;
  }
};

async function createDemoParticipant(connectionId, name) {
  return api("/social/participants", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({display_name: name, provider_connection_id: connectionId, is_demo: true})
  });
}

$("start-demo").onclick = async () => {
  const progress = $("demo-progress");
  progress.textContent = "Step 1 of 3: creating the synthetic Meta connection...";
  $("start-demo").disabled = true;
  try {
    const start = await api("/social/oauth/meta/start");
    const callback = start.mode === "demo"
      ? await api(`/social/oauth/callback?state=${encodeURIComponent(start.state)}&code=demo`)
      : (location.href = start.authorization_url);
    if (!callback) return;
    progress.textContent = "Step 2 of 3: loading synthetic post metrics...";
    await api("/social/analytics/demo", {method: "POST"});
    await api("/login-activity/demo", {method: "POST"});
    progress.textContent = "Step 3 of 3: creating synthetic participant invitations...";
    const participants = await api("/social/participants");
    const existingDemoNames = new Set(participants.filter(item => item.is_demo).map(item => item.display_name));
    const invitations = [];
    for (const name of ["Synthetic creator A", "Synthetic creator B", "Synthetic creator C"]) {
      if (!existingDemoNames.has(name)) invitations.push(await createDemoParticipant(callback.connection_id, name));
    }
    $("participant-invitation-status").replaceChildren();
    $("participant-invitation-status").appendChild(document.createTextNode(
      "Synthetic invitations are ready. Participants must confirm consent themselves; no invitation was emailed."
    ));
    invitations.forEach(result => {
      const item = document.createElement("div");
      item.className = "invitation";
      item.appendChild(badge("Demo data"));
      item.appendChild(document.createTextNode(`Consent link for ${result.participant.display_name}: `));
      const link = `${location.origin}/social/participants/${result.participant.id}/consent?token=${encodeURIComponent(result.consent_token)}`;
      const code = document.createElement("code");
      code.textContent = link;
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "button-secondary";
      copy.textContent = "Copy";
      copy.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(link);
          copy.textContent = "Copied";
        } catch {
          copy.textContent = "Copy failed";
        }
      });
      item.append(" ", code, " ", copy);
      $("participant-invitation-status").appendChild(item);
    });
    progress.textContent = "Demo ready: review Connected Accounts, Organic IDs, and Diagnosis below. Metrics are synthetic.";
    await loadSocial();
    await loadLoginActivity();
    document.getElementById("social-accounts-panel").scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) {
    progress.textContent = `Demo stopped: ${error.message} Retry Start Demo; completed steps remain visible.`;
  } finally {
    $("start-demo").disabled = false;
  }
};

$("reset-demo").onclick = async () => {
  if (!window.confirm("Reset only synthetic demo connections, participants, and metrics? Real records will be preserved.")) return;
  const progress = $("demo-progress");
  progress.textContent = "Resetting synthetic demo data...";
  try {
    const result = await api("/social/demo-data", {method: "DELETE"});
    progress.textContent = `Demo data reset. Removed ${result.connections_deleted} connection${result.connections_deleted === 1 ? "" : "s"}, ${result.participants_deleted} participant${result.participants_deleted === 1 ? "" : "s"}, and ${result.metrics_deleted} metric${result.metrics_deleted === 1 ? "" : "s"}.`;
    $("participant-invitation-status").textContent = "";
    await loadSocial();
    await loadLoginActivity();
  } catch (error) {
    progress.textContent = `Could not reset demo data: ${error.message}`;
  }
};

api("/auth/me").then(user => {
  if (location.pathname === "/register" || location.pathname === "/login") {
    history.replaceState({}, "", "/");
  }
  currentUser = user;
  $("login").hidden = true;
  $("dashboard").hidden = false;
  $("current-user").textContent = `Signed in as ${user.username}`;
  load();
}).catch(error => {
  renderAuthMode();
  if (error.message === "Failed to fetch") $("startup-error").textContent = "Cannot reach the server. Start Uvicorn and reload this page.";
});
