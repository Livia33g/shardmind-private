use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use chrono::Utc;
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, State};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopSettings {
    #[serde(default)]
    repo_path: String,
    #[serde(default)]
    uv_path: String,
    #[serde(default)]
    vault_path: String,
    #[serde(default)]
    sqlite_path: String,
    #[serde(default)]
    cloud_access: CloudAccessSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CloudAccessSettings {
    #[serde(default)]
    enabled: bool,
    #[serde(default)]
    account_email: String,
    #[serde(default = "default_sync_scope")]
    sync_scope: String,
    #[serde(default)]
    sync_selection: String,
    #[serde(default = "default_read_only")]
    read_only: bool,
    #[serde(default = "default_bridge_url")]
    bridge_url: String,
    #[serde(default)]
    bearer_token: String,
    #[serde(default)]
    last_sync_at: Option<String>,
    #[serde(default)]
    last_sync_message: String,
    #[serde(default)]
    last_sync_documents: usize,
    #[serde(default)]
    connected_at: Option<String>,
}

impl Default for CloudAccessSettings {
    fn default() -> Self {
        Self {
            enabled: false,
            account_email: String::new(),
            sync_scope: "selected-projects".into(),
            sync_selection: String::new(),
            read_only: true,
            bridge_url: "http://127.0.0.1:8787".into(),
            bearer_token: String::new(),
            last_sync_at: None,
            last_sync_message: String::new(),
            last_sync_documents: 0,
            connected_at: None,
        }
    }
}

impl Default for DesktopSettings {
    fn default() -> Self {
        let repo_path = repo_root_guess()
            .map(|path| path.to_string_lossy().to_string())
            .unwrap_or_default();
        Self {
            repo_path,
            uv_path: "uv".into(),
            vault_path: default_home_path("Documents/ShardMind"),
            sqlite_path: default_home_path("Library/Application Support/shardmind/shardmind.sqlite3"),
            cloud_access: CloudAccessSettings::default(),
        }
    }
}

fn default_sync_scope() -> String {
    "selected-projects".into()
}

fn default_read_only() -> bool {
    true
}

fn default_bridge_url() -> String {
    "http://127.0.0.1:8787".into()
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ServiceStatus {
    running: bool,
    started_at: Option<String>,
    command: String,
    last_error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct IntegrationStatus {
    id: String,
    label: String,
    available: bool,
    configured: bool,
    config_path: String,
    summary: String,
    action_label: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineStatus {
    installed: bool,
    source: String,
    binary_path: String,
    installer_source: String,
    summary: String,
    action_label: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct VaultAccessStatus {
    vault_path: String,
    vault_exists: bool,
    obsidian_available: bool,
    obsidian_path: String,
    summary: String,
}

#[derive(Debug, Clone)]
enum EngineLaunch {
    InstalledBinary {
        command: String,
        args: Vec<String>,
        summary: String,
    },
    RepoUv {
        command: String,
        args: Vec<String>,
        current_dir: String,
        summary: String,
    },
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct CloudAccessStatus {
    enabled: bool,
    stage: String,
    summary: String,
    local_source_of_truth: String,
    sync_scope: String,
    supported_clients: Vec<String>,
    next_steps: Vec<String>,
    bridge_status: String,
    bridge_details: String,
    last_sync_at: Option<String>,
    last_sync_message: String,
    last_sync_documents: usize,
    connected_at: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SyncManifest {
    version: String,
    generated_at: String,
    account_email: String,
    enabled: bool,
    local_source_of_truth: String,
    vault_path: String,
    sync_scope: String,
    sync_selection: Vec<String>,
    read_only: bool,
    target_clients: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct SyncUploadStatus {
    ok: bool,
    uploaded_documents: usize,
    bridge_url: String,
    message: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct CloudSessionStatus {
    account_email: String,
    session_token: String,
    message: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BridgeHealthStatus {
    ok: bool,
    summary: String,
    details: String,
}

#[derive(Default)]
struct ManagedProcess {
    child: Option<Child>,
    started_at: Option<String>,
    last_error: Option<String>,
}

struct ProcessState {
    inner: Mutex<ManagedProcess>,
}

impl Default for ProcessState {
    fn default() -> Self {
        Self {
            inner: Mutex::new(ManagedProcess::default()),
        }
    }
}

#[tauri::command]
fn load_settings(app: AppHandle) -> Result<DesktopSettings, String> {
    read_settings(&app)
}

#[tauri::command]
fn save_settings(app: AppHandle, settings: DesktopSettings) -> Result<DesktopSettings, String> {
    write_settings(&app, &settings)?;
    Ok(settings)
}

#[tauri::command]
fn engine_status(app: AppHandle) -> Result<EngineStatus, String> {
    let settings = read_settings(&app)?;
    Ok(engine_status_for(&app, &settings))
}

#[tauri::command]
fn install_engine(app: AppHandle) -> Result<EngineStatus, String> {
    let settings = read_settings(&app)?;
    install_managed_engine(&app, &settings)?;
    Ok(engine_status_for(&app, &settings))
}

#[tauri::command]
fn vault_access_status(app: AppHandle) -> Result<VaultAccessStatus, String> {
    let settings = read_settings(&app)?;
    Ok(vault_access_status_for(&settings))
}

#[tauri::command]
fn open_vault_folder(app: AppHandle) -> Result<(), String> {
    let settings = read_settings(&app)?;
    let vault_path = PathBuf::from(settings.vault_path.trim());
    if settings.vault_path.trim().is_empty() {
        return Err("Vault path is not set yet.".into());
    }
    if !vault_path.exists() {
        return Err("Vault path does not exist on disk.".into());
    }

    Command::new("open")
        .arg(&vault_path)
        .status()
        .map_err(|error| format!("Failed to open vault folder: {error}"))
        .and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                Err("macOS could not open the vault folder.".into())
            }
        })
}

#[tauri::command]
fn open_in_obsidian(app: AppHandle) -> Result<(), String> {
    let settings = read_settings(&app)?;
    let vault_path = PathBuf::from(settings.vault_path.trim());
    if settings.vault_path.trim().is_empty() {
        return Err("Vault path is not set yet.".into());
    }
    if !vault_path.exists() {
        return Err("Vault path does not exist on disk.".into());
    }
    let obsidian_path =
        obsidian_app_path().ok_or_else(|| "Obsidian.app was not found on this machine.".to_string())?;

    Command::new("open")
        .arg("-a")
        .arg(obsidian_path)
        .arg(&vault_path)
        .status()
        .map_err(|error| format!("Failed to open vault in Obsidian: {error}"))
        .and_then(|status| {
            if status.success() {
                Ok(())
            } else {
                Err("macOS could not open the vault in Obsidian.".into())
            }
        })
}

#[tauri::command]
fn service_status(app: AppHandle, state: State<ProcessState>) -> Result<ServiceStatus, String> {
    let settings = read_settings(&app)?;
    let command = launch_command(&app, &settings)?;
    let mut process = state.inner.lock().map_err(|_| "Process lock poisoned".to_string())?;
    let running = process_running(&mut process)?;
    Ok(ServiceStatus {
        running,
        started_at: process.started_at.clone(),
        command,
        last_error: process.last_error.clone(),
    })
}

#[tauri::command]
fn start_service(app: AppHandle, state: State<ProcessState>) -> Result<ServiceStatus, String> {
    let settings = read_settings(&app)?;
    validate_settings(&app, &settings)?;
    let launch = resolve_engine_launch(&app, &settings)?;
    let command_string = launch.summary().to_string();
    let mut process = state.inner.lock().map_err(|_| "Process lock poisoned".to_string())?;

    if process_running(&mut process)? {
        return Ok(ServiceStatus {
            running: true,
            started_at: process.started_at.clone(),
            command: command_string,
            last_error: process.last_error.clone(),
        });
    }

    let mut command = Command::new(launch.command());
    command
        .args(launch.args())
        .env("SHARDMIND_VAULT_PATH", &settings.vault_path)
        .env("SHARDMIND_SQLITE_PATH", &settings.sqlite_path)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some(current_dir) = launch.current_dir() {
        command.current_dir(current_dir);
    }

    match command.spawn() {
        Ok(child) => {
            process.child = Some(child);
            process.started_at = Some(Utc::now().to_rfc3339());
            process.last_error = None;
        }
        Err(error) => {
            process.last_error = Some(error.to_string());
            return Err(format!("Failed to launch ShardMind: {error}"));
        }
    }

    Ok(ServiceStatus {
        running: true,
        started_at: process.started_at.clone(),
        command: command_string,
        last_error: None,
    })
}

#[tauri::command]
fn stop_service(app: AppHandle, state: State<ProcessState>) -> Result<ServiceStatus, String> {
    let settings = read_settings(&app)?;
    let command = launch_command(&app, &settings)?;
    let mut process = state.inner.lock().map_err(|_| "Process lock poisoned".to_string())?;
    if let Some(child) = process.child.as_mut() {
        let _ = child.kill();
        let _ = child.wait();
    }
    process.child = None;
    process.started_at = None;

    Ok(ServiceStatus {
        running: false,
        started_at: None,
        command,
        last_error: process.last_error.clone(),
    })
}

#[tauri::command]
fn detect_integrations(app: AppHandle) -> Result<Vec<IntegrationStatus>, String> {
    let settings = read_settings(&app)?;
    Ok(vec![
        detect_claude_desktop(&settings),
        detect_cursor(&settings),
        detect_codex(&settings),
        detect_gemini_cli(&settings),
        remote_only_integration(
            "chatgpt",
            "ChatGPT",
            "Optional cloud-connected mode for non-edu testers who need remote ChatGPT access",
        ),
        remote_only_integration(
            "gemini-chat",
            "Gemini Chat",
            "Planned only for now; Gemini CLI remains the real Gemini integration",
        ),
    ])
}

#[tauri::command]
fn install_integration(app: AppHandle, integration_id: String) -> Result<Vec<IntegrationStatus>, String> {
    let settings = read_settings(&app)?;
    validate_settings(&app, &settings)?;
    match integration_id.as_str() {
        "claude" => install_claude_desktop(&app, &settings)?,
        "cursor" => install_cursor(&app, &settings)?,
        "codex" => install_codex(&app, &settings)?,
        "gemini-cli" => install_gemini_cli(&app, &settings)?,
        "chatgpt" | "gemini-chat" => {
            return Err("This integration will need a cloud bridge rather than local MCP config.".into())
        }
        _ => return Err(format!("Unsupported integration '{integration_id}'.")),
    }
    detect_integrations(app)
}

#[tauri::command]
fn load_cloud_access_settings(app: AppHandle) -> Result<CloudAccessSettings, String> {
    Ok(read_settings(&app)?.cloud_access)
}

#[tauri::command]
fn save_cloud_access_settings(
    app: AppHandle,
    cloud_access: CloudAccessSettings,
) -> Result<CloudAccessStatus, String> {
    let mut settings = read_settings(&app)?;
    settings.cloud_access = cloud_access;
    validate_settings(&app, &settings)?;
    write_settings(&app, &settings)?;
    Ok(cloud_access_status_for(&settings))
}

#[tauri::command]
fn bridge_health(app: AppHandle) -> Result<BridgeHealthStatus, String> {
    let settings = read_settings(&app)?;
    Ok(bridge_health_for(&settings))
}

#[tauri::command]
fn cloud_access_status_for_current_settings(app: AppHandle) -> Result<CloudAccessStatus, String> {
    let settings = read_settings(&app)?;
    Ok(cloud_access_status_for(&settings))
}

#[tauri::command]
fn preview_sync_manifest(app: AppHandle) -> Result<SyncManifest, String> {
    let settings = read_settings(&app)?;
    Ok(sync_manifest_for(&settings))
}

#[tauri::command]
fn export_sync_manifest(app: AppHandle) -> Result<String, String> {
    let settings = read_settings(&app)?;
    let manifest = sync_manifest_for(&settings);
    let base = app
        .path()
        .app_config_dir()
        .map_err(|error| error.to_string())?;
    fs::create_dir_all(&base).map_err(|error| error.to_string())?;
    let path = base.join("cloud-sync-manifest.json");
    let raw = serde_json::to_string_pretty(&manifest).map_err(|error| error.to_string())?;
    fs::write(&path, raw).map_err(|error| error.to_string())?;
    Ok(path.display().to_string())
}

#[tauri::command]
fn upload_sync_bundle(app: AppHandle) -> Result<SyncUploadStatus, String> {
    let mut settings = read_settings(&app)?;
    validate_settings(&app, &settings)?;
    let cloud = settings.cloud_access.clone();
    if !cloud.enabled {
        return Err("Enable Cloud-Connected Mode before uploading a sync bundle.".into());
    }
    if cloud.account_email.trim().is_empty() {
        return Err("Account email is required before uploading a sync bundle.".into());
    }
    if cloud.bridge_url.trim().is_empty() {
        return Err("Bridge URL is required for cloud upload.".into());
    }

    let output = Command::new(&settings.uv_path)
        .arg("--directory")
        .arg(&settings.repo_path)
        .arg("run")
        .arg("--frozen")
        .arg("shardmind")
        .arg("export-cloud-bundle")
        .arg("--selection")
        .arg(&cloud.sync_selection)
        .current_dir(&settings.repo_path)
        .env("SHARDMIND_VAULT_PATH", &settings.vault_path)
        .env("SHARDMIND_SQLITE_PATH", &settings.sqlite_path)
        .output()
        .map_err(|error| format!("Failed to export local cloud bundle: {error}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Cloud bundle export failed: {}", stderr.trim()));
    }

    let mut bundle: serde_json::Value =
        serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())?;
    let manifest = bundle
        .get_mut("manifest")
        .and_then(serde_json::Value::as_object_mut)
        .ok_or_else(|| "Exported bundle is missing a manifest object.".to_string())?;
    manifest.insert(
        "account_email".into(),
        serde_json::Value::String(cloud.account_email.clone()),
    );
    manifest.insert(
        "sync_scope".into(),
        serde_json::Value::String(cloud.sync_scope.clone()),
    );
    manifest.insert(
        "read_only".into(),
        serde_json::Value::Bool(cloud.read_only),
    );
    manifest.insert(
        "target_clients".into(),
        serde_json::json!(["ChatGPT"]),
    );

    let uploaded_documents = bundle
        .get("documents")
        .and_then(serde_json::Value::as_array)
        .map_or(0, |documents| documents.len());

    let client = Client::new();
    let mut request = client
        .post(format!("{}/v1/sync/bundle", cloud.bridge_url.trim_end_matches('/')))
        .json(&bundle);
    if !cloud.bearer_token.trim().is_empty() {
        request = request.bearer_auth(cloud.bearer_token.trim());
    }
    let response = request.send().map_err(|error| format!("Upload failed: {error}"))?;
    if !response.status().is_success() {
        let body = response.text().unwrap_or_default();
        return Err(format!("Bridge rejected sync bundle: {body}"));
    }

    settings.cloud_access.last_sync_at = Some(Utc::now().to_rfc3339());
    settings.cloud_access.last_sync_documents = uploaded_documents;
    settings.cloud_access.last_sync_message = "Sync bundle uploaded to the hosted bridge.".into();
    write_settings(&app, &settings)?;

    Ok(SyncUploadStatus {
        ok: true,
        uploaded_documents,
        bridge_url: cloud.bridge_url.clone(),
        message: "Sync bundle uploaded to the hosted bridge.".into(),
    })
}

#[tauri::command]
fn connect_cloud_account(app: AppHandle) -> Result<CloudSessionStatus, String> {
    let mut settings = read_settings(&app)?;
    validate_settings(&app, &settings)?;
    let cloud = &settings.cloud_access;
    if !cloud.enabled {
        return Err("Enable Cloud-Connected Mode before connecting an account.".into());
    }
    if cloud.account_email.trim().is_empty() {
        return Err("Account email is required before connecting an account.".into());
    }
    if cloud.bridge_url.trim().is_empty() {
        return Err("Bridge URL is required before connecting an account.".into());
    }

    let client = Client::new();
    let mut request = client
        .post(format!("{}/v1/account/session", cloud.bridge_url.trim_end_matches('/')))
        .json(&serde_json::json!({
            "account_email": cloud.account_email.trim(),
        }));
    if !cloud.bearer_token.trim().is_empty() {
        request = request.bearer_auth(cloud.bearer_token.trim());
    }

    let response = request
        .send()
        .map_err(|error| format!("Account connection failed: {error}"))?;
    if !response.status().is_success() {
        let body = response.text().unwrap_or_default();
        return Err(format!("Bridge rejected account connection: {body}"));
    }

    let payload: serde_json::Value = response.json().map_err(|error| error.to_string())?;
    let result = payload
        .get("result")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| "Bridge response is missing a result payload.".to_string())?;
    let session_token = result
        .get("session_token")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "Bridge response is missing a session token.".to_string())?
        .to_string();

    settings.cloud_access.bearer_token = session_token.clone();
    settings.cloud_access.connected_at = Some(Utc::now().to_rfc3339());
    write_settings(&app, &settings)?;

    Ok(CloudSessionStatus {
        account_email: settings.cloud_access.account_email.clone(),
        session_token,
        message: "Account connected. The desktop app is now using an account session token.".into(),
    })
}

fn process_running(process: &mut ManagedProcess) -> Result<bool, String> {
    if let Some(child) = process.child.as_mut() {
        match child.try_wait().map_err(|error| error.to_string())? {
            Some(status) => {
                process.child = None;
                process.started_at = None;
                if !status.success() {
                    process.last_error = Some(format!("ShardMind exited with status {status}"));
                }
                Ok(false)
            }
            None => Ok(true),
        }
    } else {
        Ok(false)
    }
}

fn validate_settings(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    if settings.vault_path.trim().is_empty() {
        return Err("Vault path is required.".into());
    }
    if settings.sqlite_path.trim().is_empty() {
        return Err("SQLite path is required.".into());
    }
    if settings.cloud_access.enabled && settings.cloud_access.account_email.trim().is_empty() {
        return Err("Account email is required when cloud access is enabled.".into());
    }
    if settings.cloud_access.enabled && settings.cloud_access.bridge_url.trim().is_empty() {
        return Err("Bridge URL is required when cloud access is enabled.".into());
    }
    resolve_engine_launch(app, settings)?;
    Ok(())
}

fn cloud_access_status_for(settings: &DesktopSettings) -> CloudAccessStatus {
    let cloud = &settings.cloud_access;
    let bridge_health = bridge_health_for(settings);
    let summary = if cloud.enabled {
        format!(
            "Cloud-connected mode is configured for {}. Use this only when a tester specifically needs ChatGPT-style remote access.",
            cloud.account_email
        )
    } else {
        "Cloud-connected access is optional. For current alpha testing, local clients like Claude Desktop, Cursor, Codex, and Gemini CLI are the recommended path.".into()
    };
    let sync_scope = if cloud.enabled {
        format!(
            "{} | selection: {} | mode: {}",
            cloud.sync_scope,
            blank_as_placeholder(&cloud.sync_selection),
            if cloud.read_only { "read/search only" } else { "writes later" }
        )
    } else {
        "Recommended MVP: read/search only with selective sync.".into()
    };
    CloudAccessStatus {
        enabled: cloud.enabled,
        stage: if cloud.enabled { "Configured".into() } else { "Planned".into() },
        summary,
        local_source_of_truth: "The local ShardMind vault remains canonical.".into(),
        sync_scope,
        supported_clients: vec!["ChatGPT".into()],
        next_steps: if cloud.enabled {
            vec![
                "Use this mode only for testers who specifically need ChatGPT-style remote access.".into(),
                "Local alpha testers should usually start with Claude Desktop, Cursor, Codex, or Gemini CLI.".into(),
                "Keep the local vault canonical and sync selectively.".into(),
                "Validate the hosted ChatGPT flow only after local setup is stable.".into(),
            ]
        } else {
            vec![
                "Start alpha testers on local clients first.".into(),
                "Use the Install buttons below for Claude Desktop, Cursor, Codex, or Gemini CLI.".into(),
                "Keep cloud mode as an optional later step for non-edu ChatGPT testers.".into(),
                "Do not require hosted sync unless a tester truly needs remote assistant access.".into(),
            ]
        },
        bridge_status: bridge_health.summary,
        bridge_details: bridge_health.details,
        last_sync_at: cloud.last_sync_at.clone(),
        last_sync_message: cloud.last_sync_message.clone(),
        last_sync_documents: cloud.last_sync_documents,
        connected_at: cloud.connected_at.clone(),
    }
}

fn bridge_health_for(settings: &DesktopSettings) -> BridgeHealthStatus {
    let cloud = &settings.cloud_access;
    if cloud.bridge_url.trim().is_empty() {
        return BridgeHealthStatus {
            ok: false,
            summary: "Bridge URL missing".into(),
            details: "Set a bridge URL to test cloud connectivity.".into(),
        };
    }

    let client = Client::new();
    let mut request = client.get(format!("{}/health", cloud.bridge_url.trim_end_matches('/')));
    if !cloud.bearer_token.trim().is_empty() {
        request = request.bearer_auth(cloud.bearer_token.trim());
    }

    match request.send() {
        Ok(response) => {
            if !response.status().is_success() {
                return BridgeHealthStatus {
                    ok: false,
                    summary: format!("Bridge responded with {}", response.status()),
                    details: "The hosted bridge is reachable, but rejected the current credentials.".into(),
                };
            }
            let payload = response.json::<serde_json::Value>().ok();
            let authenticated_as = payload
                .as_ref()
                .and_then(|value| value.get("authenticated_as"))
                .and_then(serde_json::Value::as_str)
                .unwrap_or("unknown");
            let synced_accounts = payload
                .as_ref()
                .and_then(|value| value.get("synced_accounts"))
                .and_then(serde_json::Value::as_u64)
                .unwrap_or(0);
            BridgeHealthStatus {
                ok: true,
                summary: "Bridge reachable".into(),
                details: format!(
                    "Authenticated as {authenticated_as}. Synced accounts in this bridge: {synced_accounts}."
                ),
            }
        }
        Err(error) => BridgeHealthStatus {
            ok: false,
            summary: "Bridge offline".into(),
            details: format!("Could not reach the hosted bridge: {error}"),
        },
    }
}

fn sync_manifest_for(settings: &DesktopSettings) -> SyncManifest {
    let cloud = &settings.cloud_access;
    SyncManifest {
        version: "0.1".into(),
        generated_at: Utc::now().to_rfc3339(),
        account_email: cloud.account_email.clone(),
        enabled: cloud.enabled,
        local_source_of_truth: "local-shardmind-vault".into(),
        vault_path: settings.vault_path.clone(),
        sync_scope: cloud.sync_scope.clone(),
        sync_selection: split_sync_selection(&cloud.sync_selection),
        read_only: cloud.read_only,
        target_clients: vec!["ChatGPT".into()],
    }
}

fn detect_claude_desktop(_settings: &DesktopSettings) -> IntegrationStatus {
    let path = home_path("Library/Application Support/Claude/claude_desktop_config.json");
    let available = path.parent().is_some_and(Path::exists);
    let configured = json_mcp_server_exists(&path, "ShardMind");
    IntegrationStatus {
        id: "claude".into(),
        label: "Claude Desktop".into(),
        available,
        configured,
        config_path: path.display().to_string(),
        summary: if configured {
            "ShardMind MCP entry is installed.".into()
        } else if available {
            "Claude config found, but ShardMind is not installed yet.".into()
        } else {
            "Claude Desktop config directory not found on this machine.".into()
        },
        action_label: available.then_some(if configured { "Repair".into() } else { "Install".into() }),
    }
}

fn detect_codex(_settings: &DesktopSettings) -> IntegrationStatus {
    let path = home_path(".codex/config.toml");
    let available = path.parent().is_some_and(Path::exists);
    let configured = toml_mcp_server_exists(&path, "shardmind");
    IntegrationStatus {
        id: "codex".into(),
        label: "Codex".into(),
        available,
        configured,
        config_path: path.display().to_string(),
        summary: if configured {
            "Codex stdio integration is installed.".into()
        } else if available {
            "Codex config found, but ShardMind is not installed yet.".into()
        } else {
            "Codex config directory not found on this machine.".into()
        },
        action_label: available.then_some(if configured { "Repair".into() } else { "Install".into() }),
    }
}

fn detect_cursor(_settings: &DesktopSettings) -> IntegrationStatus {
    let path = home_path(".cursor/mcp.json");
    let available = path.parent().is_some_and(Path::exists);
    let configured = json_mcp_server_exists(&path, "ShardMind");
    IntegrationStatus {
        id: "cursor".into(),
        label: "Cursor".into(),
        available,
        configured,
        config_path: path.display().to_string(),
        summary: if configured {
            "Cursor MCP integration is installed.".into()
        } else if available {
            "Cursor MCP config found, but ShardMind is not installed yet.".into()
        } else {
            "Cursor config directory not found on this machine.".into()
        },
        action_label: available.then_some(if configured { "Repair".into() } else { "Install".into() }),
    }
}

fn detect_gemini_cli(_settings: &DesktopSettings) -> IntegrationStatus {
    let path = home_path(".gemini/settings.json");
    let available = path.parent().is_some_and(Path::exists);
    let configured = json_mcp_server_exists(&path, "shardmind");
    IntegrationStatus {
        id: "gemini-cli".into(),
        label: "Gemini CLI".into(),
        available,
        configured,
        config_path: path.display().to_string(),
        summary: if configured {
            "Gemini CLI stdio integration is installed.".into()
        } else if available {
            "Gemini settings found, but ShardMind is not installed yet.".into()
        } else {
            "Gemini CLI settings directory not found on this machine.".into()
        },
        action_label: available.then_some(if configured { "Repair".into() } else { "Install".into() }),
    }
}

fn remote_only_integration(id: &str, label: &str, summary: &str) -> IntegrationStatus {
    IntegrationStatus {
        id: id.into(),
        label: label.into(),
        available: true,
        configured: false,
        config_path: "-".into(),
        summary: summary.into(),
        action_label: None,
    }
}

fn install_claude_desktop(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    let path = home_path("Library/Application Support/Claude/claude_desktop_config.json");
    ensure_parent_dir(&path)?;
    let mut root = read_json_value(&path).unwrap_or_else(|| serde_json::json!({}));
    if !root.is_object() {
        root = serde_json::json!({});
    }
    let mcp_servers = root
        .as_object_mut()
        .expect("root object")
        .entry("mcpServers")
        .or_insert_with(|| serde_json::json!({}));
    if !mcp_servers.is_object() {
        *mcp_servers = serde_json::json!({});
    }
    mcp_servers["ShardMind"] = local_stdio_server_json(app, settings);
    write_json_value(&path, &root)
}

fn install_gemini_cli(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    let path = home_path(".gemini/settings.json");
    ensure_parent_dir(&path)?;
    let mut root = read_json_value(&path).unwrap_or_else(|| serde_json::json!({}));
    if !root.is_object() {
        root = serde_json::json!({});
    }
    let mcp_servers = root
        .as_object_mut()
        .expect("root object")
        .entry("mcpServers")
        .or_insert_with(|| serde_json::json!({}));
    if !mcp_servers.is_object() {
        *mcp_servers = serde_json::json!({});
    }
    mcp_servers["shardmind"] = local_stdio_server_json(app, settings);
    write_json_value(&path, &root)
}

fn install_cursor(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    let path = home_path(".cursor/mcp.json");
    ensure_parent_dir(&path)?;
    let mut root = read_json_value(&path).unwrap_or_else(|| serde_json::json!({}));
    if !root.is_object() {
        root = serde_json::json!({});
    }
    let mcp_servers = root
        .as_object_mut()
        .expect("root object")
        .entry("mcpServers")
        .or_insert_with(|| serde_json::json!({}));
    if !mcp_servers.is_object() {
        *mcp_servers = serde_json::json!({});
    }
    mcp_servers["ShardMind"] = local_stdio_server_json(app, settings);
    write_json_value(&path, &root)
}

fn install_codex(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    let path = home_path(".codex/config.toml");
    ensure_parent_dir(&path)?;
    let mut root = read_toml_value(&path).unwrap_or_else(|| toml::Value::Table(Default::default()));
    let table = root
        .as_table_mut()
        .ok_or_else(|| "Codex config is not a TOML table.".to_string())?;
    let mcp_servers = table
        .entry("mcp_servers")
        .or_insert_with(|| toml::Value::Table(Default::default()));
    if !mcp_servers.is_table() {
        *mcp_servers = toml::Value::Table(Default::default());
    }
    let launch = resolve_engine_launch(app, settings)?;
    let mut env_table = toml::map::Map::new();
    env_table.insert(
        "SHARDMIND_VAULT_PATH".into(),
        toml::Value::String(settings.vault_path.clone()),
    );
    env_table.insert(
        "SHARDMIND_SQLITE_PATH".into(),
        toml::Value::String(settings.sqlite_path.clone()),
    );

    let mut server_map = toml::map::Map::new();
    server_map.insert("command".into(), toml::Value::String(launch.command().to_string()));
    server_map.insert(
        "args".into(),
        toml::Value::Array(
            launch
                .args()
                .iter()
                .cloned()
                .map(toml::Value::String)
                .collect(),
        ),
    );
    server_map.insert("env".into(), toml::Value::Table(env_table));
    let server_table = toml::Value::Table(server_map);
    mcp_servers
        .as_table_mut()
        .expect("mcp_servers table")
        .insert("shardmind".into(), server_table);
    write_toml_value(&path, &root)
}

fn local_stdio_server_json(app: &AppHandle, settings: &DesktopSettings) -> serde_json::Value {
    let launch = resolve_engine_launch(app, settings).unwrap_or_else(|_| EngineLaunch::RepoUv {
        command: settings.uv_path.clone(),
        args: vec![
            "--directory".into(),
            settings.repo_path.clone(),
            "run".into(),
            "--frozen".into(),
            "shardmind-mcp".into(),
        ],
        current_dir: settings.repo_path.clone(),
        summary: format!(
            "{} --directory {} run --frozen shardmind-mcp",
            settings.uv_path, settings.repo_path
        ),
    });
    serde_json::json!({
        "command": launch.command(),
        "args": launch.args(),
        "env": {
            "SHARDMIND_VAULT_PATH": settings.vault_path,
            "SHARDMIND_SQLITE_PATH": settings.sqlite_path
        }
    })
}

fn json_mcp_server_exists(path: &Path, server_name: &str) -> bool {
    read_json_value(path)
        .and_then(|root| root.get("mcpServers").cloned())
        .and_then(|servers| servers.get(server_name).cloned())
        .is_some()
}

fn toml_mcp_server_exists(path: &Path, server_name: &str) -> bool {
    read_toml_value(path)
        .and_then(|root| root.get("mcp_servers").cloned())
        .and_then(|servers| servers.get(server_name).cloned())
        .is_some()
}

fn read_json_value(path: &Path) -> Option<serde_json::Value> {
    fs::read_to_string(path)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
}

fn write_json_value(path: &Path, value: &serde_json::Value) -> Result<(), String> {
    let raw = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    fs::write(path, raw).map_err(|error| error.to_string())
}

fn read_toml_value(path: &Path) -> Option<toml::Value> {
    fs::read_to_string(path)
        .ok()
        .and_then(|raw| toml::from_str(&raw).ok())
}

fn write_toml_value(path: &Path, value: &toml::Value) -> Result<(), String> {
    let raw = toml::to_string_pretty(value).map_err(|error| error.to_string())?;
    fs::write(path, raw).map_err(|error| error.to_string())
}

fn ensure_parent_dir(path: &Path) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    let base = app
        .path()
        .app_config_dir()
        .map_err(|error| error.to_string())?;
    fs::create_dir_all(&base).map_err(|error| error.to_string())?;
    Ok(base.join("settings.json"))
}

fn read_settings(app: &AppHandle) -> Result<DesktopSettings, String> {
    let path = settings_path(app)?;
    if !path.exists() {
        let defaults = DesktopSettings::default();
        write_settings(app, &defaults)?;
        return Ok(defaults);
    }
    let raw = fs::read_to_string(path).map_err(|error| error.to_string())?;
    serde_json::from_str(&raw).map_err(|error| error.to_string())
}

fn write_settings(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    let path = settings_path(app)?;
    let raw = serde_json::to_string_pretty(settings).map_err(|error| error.to_string())?;
    fs::write(path, raw).map_err(|error| error.to_string())
}

fn repo_root_guess() -> Option<PathBuf> {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .map(|path| path.to_path_buf())
}

fn default_home_path(suffix: &str) -> String {
    std::env::var("HOME")
        .map(|home| format!("{home}/{suffix}"))
        .unwrap_or_default()
}

fn blank_as_placeholder(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        "nothing selected yet".into()
    } else {
        trimmed.into()
    }
}

fn split_sync_selection(value: &str) -> Vec<String> {
    value
        .split(',')
        .map(str::trim)
        .filter(|entry| !entry.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

fn home_path(suffix: &str) -> PathBuf {
    PathBuf::from(default_home_path(suffix))
}

impl EngineLaunch {
    fn command(&self) -> &str {
        match self {
            Self::InstalledBinary { command, .. } | Self::RepoUv { command, .. } => command,
        }
    }

    fn args(&self) -> &[String] {
        match self {
            Self::InstalledBinary { args, .. } | Self::RepoUv { args, .. } => args,
        }
    }

    fn current_dir(&self) -> Option<&str> {
        match self {
            Self::InstalledBinary { .. } => None,
            Self::RepoUv { current_dir, .. } => Some(current_dir.as_str()),
        }
    }

    fn summary(&self) -> &str {
        match self {
            Self::InstalledBinary { summary, .. } | Self::RepoUv { summary, .. } => summary,
        }
    }
}

fn resolve_engine_launch(app: &AppHandle, settings: &DesktopSettings) -> Result<EngineLaunch, String> {
    let managed_binary = managed_engine_binary(app)?;
    if managed_binary.is_file() {
        let command = managed_binary.to_string_lossy().to_string();
        return Ok(EngineLaunch::InstalledBinary {
            summary: format!("{command} (managed by ShardMind Desktop)"),
            command,
            args: Vec::new(),
        });
    }

    if let Some(binary) = find_command_on_path("shardmind-mcp") {
        let command = binary.to_string_lossy().to_string();
        return Ok(EngineLaunch::InstalledBinary {
            summary: format!("{command} (installed ShardMind engine)"),
            command,
            args: Vec::new(),
        });
    }

    if settings.repo_path.trim().is_empty() {
        return Err(
            "Repo path is required unless shardmind-mcp is already installed on this machine."
                .into(),
        );
    }
    if settings.uv_path.trim().is_empty() {
        return Err("uv path is required when launching from a local repo checkout.".into());
    }

    Ok(EngineLaunch::RepoUv {
        summary: format!(
            "{} --directory {} run --frozen shardmind-mcp",
            settings.uv_path, settings.repo_path
        ),
        command: settings.uv_path.clone(),
        args: vec![
            "--directory".into(),
            settings.repo_path.clone(),
            "run".into(),
            "--frozen".into(),
            "shardmind-mcp".into(),
        ],
        current_dir: settings.repo_path.clone(),
    })
}

fn find_command_on_path(command: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|entry| entry.join(command))
        .find(|candidate| candidate.is_file())
}

fn launch_command(app: &AppHandle, settings: &DesktopSettings) -> Result<String, String> {
    Ok(resolve_engine_launch(app, settings)?.summary().to_string())
}

fn engine_status_for(app: &AppHandle, settings: &DesktopSettings) -> EngineStatus {
    let managed_binary = managed_engine_binary(app).ok();
    let bundled_wheel = bundled_wheel_path(app, settings).ok();

    if let Some(binary) = managed_binary.as_ref().filter(|path| path.is_file()) {
        return EngineStatus {
            installed: true,
            source: "managed".into(),
            binary_path: binary.display().to_string(),
            installer_source: bundled_wheel
                .as_ref()
                .map(|path| path.display().to_string())
                .unwrap_or_else(|| "-".into()),
            summary: "Managed engine installed inside ShardMind Desktop.".into(),
            action_label: Some("Reinstall Engine".into()),
        };
    }

    if let Some(binary) = find_command_on_path("shardmind-mcp") {
        return EngineStatus {
            installed: true,
            source: "system".into(),
            binary_path: binary.display().to_string(),
            installer_source: bundled_wheel
                .as_ref()
                .map(|path| path.display().to_string())
                .unwrap_or_else(|| "-".into()),
            summary: "System ShardMind engine detected. You can keep using it or install a managed copy.".into(),
            action_label: bundled_wheel
                .is_some()
                .then_some("Install Managed Engine".into()),
        };
    }

    let python_available = find_python_command().is_some();
    EngineStatus {
        installed: false,
        source: "missing".into(),
        binary_path: "-".into(),
        installer_source: bundled_wheel
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "-".into()),
        summary: if python_available {
            "No ShardMind engine found yet. Install a managed copy to remove manual setup steps.".into()
        } else {
            "No ShardMind engine found, and Python 3 is not currently available on this machine.".into()
        },
        action_label: if python_available && bundled_wheel.is_some() {
            Some("Install Engine".into())
        } else {
            None
        },
    }
}

fn vault_access_status_for(settings: &DesktopSettings) -> VaultAccessStatus {
    let vault_path = settings.vault_path.trim().to_string();
    let vault_exists = !vault_path.is_empty() && Path::new(&vault_path).exists();
    let obsidian_path = obsidian_app_path();
    let obsidian_available = obsidian_path.is_some();
    VaultAccessStatus {
        summary: if vault_exists {
            if obsidian_available {
                "Open the ShardMind vault folder directly or jump into Obsidian.".into()
            } else {
                "Vault found. You can open the folder directly from here.".into()
            }
        } else if vault_path.is_empty() {
            "Set a vault path first so ShardMind and Obsidian point at the same notes.".into()
        } else {
            "The current vault path does not exist yet.".into()
        },
        vault_path,
        vault_exists,
        obsidian_available,
        obsidian_path: obsidian_path
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "-".into()),
    }
}

fn install_managed_engine(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    let python = find_python_command()
        .ok_or_else(|| "Python 3 is required before ShardMind Desktop can install the engine.".to_string())?;
    let wheel = bundled_wheel_path(app, settings)?;
    let venv_dir = managed_engine_dir(app)?;
    let venv_python = managed_engine_python(app)?;

    if !venv_python.is_file() {
        ensure_parent_dir(&venv_dir)?;
        let status = Command::new(&python)
            .arg("-m")
            .arg("venv")
            .arg(&venv_dir)
            .status()
            .map_err(|error| format!("Failed to create managed ShardMind environment: {error}"))?;
        if !status.success() {
            return Err("Creating the managed ShardMind environment failed.".into());
        }
    }

    let status = Command::new(&venv_python)
        .arg("-m")
        .arg("pip")
        .arg("install")
        .arg("--upgrade")
        .arg(&wheel)
        .status()
        .map_err(|error| format!("Failed to install managed ShardMind engine: {error}"))?;
    if !status.success() {
        return Err("Installing the managed ShardMind engine failed.".into());
    }
    Ok(())
}

fn managed_engine_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let base = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    fs::create_dir_all(&base).map_err(|error| error.to_string())?;
    Ok(base.join("engine-venv"))
}

fn managed_engine_binary(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(managed_engine_dir(app)?.join("bin/shardmind-mcp"))
}

fn managed_engine_python(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(managed_engine_dir(app)?.join("bin/python"))
}

fn find_python_command() -> Option<PathBuf> {
    find_command_on_path("python3").or_else(|| find_command_on_path("python"))
}

fn obsidian_app_path() -> Option<PathBuf> {
    let system = PathBuf::from("/Applications/Obsidian.app");
    if system.exists() {
        return Some(system);
    }
    let user = home_path("Applications/Obsidian.app");
    if user.exists() {
        return Some(user);
    }
    None
}

fn bundled_wheel_path(app: &AppHandle, settings: &DesktopSettings) -> Result<PathBuf, String> {
    if let Ok(resource_dir) = app.path().resource_dir() {
        if let Some(path) = find_first_wheel(&resource_dir) {
            return Ok(path);
        }
    }

    if !settings.repo_path.trim().is_empty() {
        let repo_dist = Path::new(&settings.repo_path).join("dist");
        if let Some(path) = find_first_wheel(&repo_dist) {
            return Ok(path);
        }
    }

    if let Some(repo_root) = repo_root_guess() {
        if let Some(path) = find_first_wheel(&repo_root.join("dist")) {
            return Ok(path);
        }
    }

    Err("No bundled ShardMind wheel was found for managed installation.".into())
}

fn find_first_wheel(dir: &Path) -> Option<PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    while let Some(next_dir) = stack.pop() {
        let mut entries = fs::read_dir(&next_dir).ok()?.flatten().collect::<Vec<_>>();
        entries.sort_by_key(|entry| entry.path());
        for entry in entries {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
            } else if path.extension().is_some_and(|ext| ext == "whl") {
                return Some(path);
            }
        }
    }
    None
}

pub fn run() {
    tauri::Builder::default()
        .manage(ProcessState::default())
        .invoke_handler(tauri::generate_handler![
            load_settings,
            save_settings,
            engine_status,
            install_engine,
            vault_access_status,
            open_vault_folder,
            open_in_obsidian,
            service_status,
            start_service,
            stop_service,
            detect_integrations,
            install_integration,
            load_cloud_access_settings,
            save_cloud_access_settings,
            cloud_access_status_for_current_settings,
            bridge_health,
            preview_sync_manifest,
            export_sync_manifest,
            upload_sync_bundle,
            connect_cloud_account
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
