import { invoke } from "@tauri-apps/api/core";
import "./styles.css";

const fields = {
  repoPath: document.querySelector("#repo-path"),
  uvPath: document.querySelector("#uv-path"),
  vaultPath: document.querySelector("#vault-path"),
  sqlitePath: document.querySelector("#sqlite-path"),
};

const statusNodes = {
  badge: document.querySelector("#status-badge"),
  running: document.querySelector("#status-running"),
  startedAt: document.querySelector("#status-started-at"),
  command: document.querySelector("#status-command"),
  error: document.querySelector("#status-error"),
};

const settingsForm = document.querySelector("#settings-form");
const startButton = document.querySelector("#start-service");
const stopButton = document.querySelector("#stop-service");
const refreshButton = document.querySelector("#refresh-status");
const refreshIntegrationsButton = document.querySelector("#refresh-integrations");
const integrationsList = document.querySelector("#integrations-list");
const cloudNodes = {
  stage: document.querySelector("#cloud-stage"),
  summary: document.querySelector("#cloud-summary"),
  source: document.querySelector("#cloud-source"),
  scope: document.querySelector("#cloud-scope"),
  clients: document.querySelector("#cloud-clients"),
  bridgeStatus: document.querySelector("#cloud-bridge-status"),
  bridgeDetails: document.querySelector("#cloud-bridge-details"),
  lastSync: document.querySelector("#cloud-last-sync"),
  lastSyncMessage: document.querySelector("#cloud-last-sync-message"),
  connectedAt: document.querySelector("#cloud-connected-at"),
  nextSteps: document.querySelector("#cloud-next-steps"),
  manifestPreview: document.querySelector("#manifest-preview"),
  manifestPath: document.querySelector("#manifest-path"),
  actionStatus: document.querySelector("#cloud-action-status"),
};
const cloudFields = {
  enabled: document.querySelector("#cloud-enabled"),
  accountEmail: document.querySelector("#cloud-account-email"),
  syncScope: document.querySelector("#cloud-sync-scope"),
  syncSelection: document.querySelector("#cloud-sync-selection"),
  readOnly: document.querySelector("#cloud-read-only"),
  bridgeUrl: document.querySelector("#cloud-bridge-url"),
  bearerToken: document.querySelector("#cloud-bearer-token"),
};
const cloudAccessForm = document.querySelector("#cloud-access-form");
const exportSyncManifestButton = document.querySelector("#export-sync-manifest");
const connectCloudAccountButton = document.querySelector("#connect-cloud-account");
const uploadSyncBundleButton = document.querySelector("#upload-sync-bundle");

function applySettings(settings) {
  fields.repoPath.value = settings.repoPath ?? "";
  fields.uvPath.value = settings.uvPath ?? "";
  fields.vaultPath.value = settings.vaultPath ?? "";
  fields.sqlitePath.value = settings.sqlitePath ?? "";
}

function renderStatus(status) {
  const running = Boolean(status.running);
  statusNodes.badge.textContent = running ? "Running" : "Stopped";
  statusNodes.badge.className = `status-badge ${running ? "status-running" : "status-idle"}`;
  statusNodes.running.textContent = running ? "Yes" : "No";
  statusNodes.startedAt.textContent = status.startedAt || "-";
  statusNodes.command.textContent = status.command || "-";
  statusNodes.error.textContent = status.lastError || "-";
}

async function loadSettings() {
  const settings = await invoke("load_settings");
  applySettings(settings);
  return settings;
}

async function refreshStatus() {
  const status = await invoke("service_status");
  renderStatus(status);
}

function renderIntegrations(integrations) {
  integrationsList.replaceChildren();

  integrations.forEach((integration) => {
    const card = document.createElement("article");
    card.className = "integration-card";

    const header = document.createElement("div");
    header.className = "integration-header";

    const titleWrap = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = integration.label;
    const subtitle = document.createElement("p");
    subtitle.className = "integration-summary";
    subtitle.textContent = integration.summary;
    titleWrap.append(title, subtitle);

    const badge = document.createElement("span");
    const state = integration.configured ? "Configured" : integration.available ? "Detected" : "Missing";
    badge.textContent = state;
    badge.className = `integration-badge ${
      integration.configured ? "integration-ready" : integration.available ? "integration-detected" : "integration-missing"
    }`;
    header.append(titleWrap, badge);

    const path = document.createElement("p");
    path.className = "integration-path monospace";
    path.textContent = integration.configPath || "-";

    const footer = document.createElement("div");
    footer.className = "integration-footer";
    if (integration.actionLabel) {
      const button = document.createElement("button");
      button.className = "button button-secondary";
      button.textContent = integration.actionLabel;
      button.addEventListener("click", async () => {
        try {
          const nextIntegrations = await invoke("install_integration", {
            integrationId: integration.id,
          });
          renderIntegrations(nextIntegrations);
        } catch (error) {
          statusNodes.error.textContent = String(error);
        }
      });
      footer.append(button);
    }

    card.append(header, path, footer);
    integrationsList.append(card);
  });
}

async function refreshIntegrations() {
  const integrations = await invoke("detect_integrations");
  renderIntegrations(integrations);
}

function renderCloudAccess(status) {
  cloudNodes.stage.textContent = status.stage || "Planned";
  cloudNodes.stage.className = `status-badge ${status.enabled ? "status-running" : "status-idle"}`;
  cloudNodes.summary.textContent = status.summary;
  cloudNodes.source.textContent = status.localSourceOfTruth || "-";
  cloudNodes.scope.textContent = status.syncScope || "-";
  cloudNodes.clients.textContent = (status.supportedClients || []).join(", ") || "-";
  cloudNodes.bridgeStatus.textContent = status.bridgeStatus || "-";
  cloudNodes.bridgeDetails.textContent = status.bridgeDetails || "-";
  cloudNodes.lastSync.textContent = status.lastSyncAt || "Not synced yet";
  cloudNodes.lastSyncMessage.textContent =
    status.lastSyncMessage
      ? `${status.lastSyncMessage}${status.lastSyncDocuments ? ` (${status.lastSyncDocuments} documents)` : ""}`
      : "No sync uploaded yet.";
  cloudNodes.connectedAt.textContent = status.connectedAt || "No account session yet";
  cloudNodes.nextSteps.replaceChildren();
  (status.nextSteps || []).forEach((step) => {
    const item = document.createElement("li");
    item.textContent = step;
    cloudNodes.nextSteps.append(item);
  });
}

function setCloudActionStatus(message, tone = "default") {
  cloudNodes.actionStatus.textContent = message;
  cloudNodes.actionStatus.className = "section-copy action-status";
  if (tone === "success") {
    cloudNodes.actionStatus.classList.add("action-status-success");
  } else if (tone === "error") {
    cloudNodes.actionStatus.classList.add("action-status-error");
  }
}

function applyCloudAccessSettings(settings) {
  cloudFields.enabled.checked = Boolean(settings.enabled);
  cloudFields.accountEmail.value = settings.accountEmail ?? "";
  cloudFields.syncScope.value = settings.syncScope ?? "selected-projects";
  cloudFields.syncSelection.value = settings.syncSelection ?? "";
  cloudFields.readOnly.checked = settings.readOnly ?? true;
  cloudFields.bridgeUrl.value = settings.bridgeUrl ?? "http://127.0.0.1:8787";
  cloudFields.bearerToken.value = settings.bearerToken ?? "";
}

async function loadCloudAccessSettings() {
  const settings = await invoke("load_cloud_access_settings");
  applyCloudAccessSettings(settings);
}

async function refreshCloudAccess() {
  const status = await invoke("cloud_access_status_for_current_settings");
  renderCloudAccess(status);
}

async function refreshBridgeHealth() {
  const health = await invoke("bridge_health");
  cloudNodes.bridgeStatus.textContent = health.summary || "-";
  cloudNodes.bridgeDetails.textContent = health.details || "-";
}

async function refreshSyncManifest() {
  const manifest = await invoke("preview_sync_manifest");
  cloudNodes.manifestPreview.textContent = JSON.stringify(manifest, null, 2);
}

async function boot() {
  try {
    await loadSettings();
    await loadCloudAccessSettings();
    await refreshStatus();
    await refreshIntegrations();
    await refreshCloudAccess();
    await refreshBridgeHealth();
    await refreshSyncManifest();
  } catch (error) {
    console.error(error);
    statusNodes.error.textContent = String(error);
  }
}

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    repoPath: fields.repoPath.value.trim(),
    uvPath: fields.uvPath.value.trim(),
    vaultPath: fields.vaultPath.value.trim(),
    sqlitePath: fields.sqlitePath.value.trim(),
  };
  try {
    await invoke("save_settings", { settings: payload });
    await refreshStatus();
    await refreshIntegrations();
  } catch (error) {
    statusNodes.error.textContent = String(error);
  }
});

startButton.addEventListener("click", async () => {
  try {
    const status = await invoke("start_service");
    renderStatus(status);
  } catch (error) {
    statusNodes.error.textContent = String(error);
  }
});

stopButton.addEventListener("click", async () => {
  try {
    const status = await invoke("stop_service");
    renderStatus(status);
  } catch (error) {
    statusNodes.error.textContent = String(error);
  }
});

refreshButton.addEventListener("click", async () => {
  await refreshStatus();
});

refreshIntegrationsButton.addEventListener("click", async () => {
  await refreshIntegrations();
});

cloudAccessForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    enabled: cloudFields.enabled.checked,
    accountEmail: cloudFields.accountEmail.value.trim(),
    syncScope: cloudFields.syncScope.value,
    syncSelection: cloudFields.syncSelection.value.trim(),
    readOnly: cloudFields.readOnly.checked,
    bridgeUrl: cloudFields.bridgeUrl.value.trim(),
    bearerToken: cloudFields.bearerToken.value.trim(),
  };
  try {
    const status = await invoke("save_cloud_access_settings", { cloudAccess: payload });
    renderCloudAccess(status);
    await refreshBridgeHealth();
    await refreshSyncManifest();
    setCloudActionStatus("Cloud access plan saved.", "success");
  } catch (error) {
    setCloudActionStatus(String(error), "error");
    statusNodes.error.textContent = String(error);
  }
});

exportSyncManifestButton.addEventListener("click", async () => {
  try {
    const path = await invoke("export_sync_manifest");
    cloudNodes.manifestPath.textContent = `Manifest exported to ${path}`;
    await refreshSyncManifest();
    setCloudActionStatus("Sync manifest exported.", "success");
  } catch (error) {
    setCloudActionStatus(String(error), "error");
    statusNodes.error.textContent = String(error);
  }
});

connectCloudAccountButton.addEventListener("click", async () => {
  try {
    setCloudActionStatus("Connecting account...");
    const status = await invoke("connect_cloud_account");
    cloudFields.bearerToken.value = status.sessionToken || "";
    setCloudActionStatus(status.message, "success");
    await refreshCloudAccess();
    await refreshBridgeHealth();
    await loadCloudAccessSettings();
  } catch (error) {
    setCloudActionStatus(String(error), "error");
    statusNodes.error.textContent = String(error);
  }
});

uploadSyncBundleButton.addEventListener("click", async () => {
  try {
    setCloudActionStatus("Uploading sync bundle...");
    const status = await invoke("upload_sync_bundle");
    cloudNodes.manifestPath.textContent = status.message;
    await refreshCloudAccess();
    await refreshBridgeHealth();
    await refreshSyncManifest();
    setCloudActionStatus(status.message, "success");
  } catch (error) {
    setCloudActionStatus(String(error), "error");
    statusNodes.error.textContent = String(error);
  }
});

boot();
