//! Wese Trade desktop shell (Tauri 2).
//!
//! The shell owns ONE local FastAPI sidecar. On launch it resolves the native app-data
//! directory, starts the sidecar on a free 127.0.0.1 port (the sidecar backs up +
//! migrates the database before serving), waits for `/health`, then navigates the window
//! to the same-origin UI served by the sidecar. On exit it stops the sidecar gracefully
//! (bounded) and never leaves an orphan process.
//!
//! The UI gets no shell, filesystem or process access: only the named commands below,
//! and only those granted in `capabilities/`.

mod backend;
mod paths;
mod smoke;

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use serde::Serialize;
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, RunEvent, Runtime, State, Url, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_log::{RotationStrategy, Target, TargetKind};
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_updater::UpdaterExt;

use backend::{Backend, Launch, Status};
use paths::RuntimePaths;

pub const MAIN: &str = "main";
const STOP_TIMEOUT: Duration = Duration::from_secs(15);

pub struct AppState {
    backend: Arc<Backend>,
    paths: RuntimePaths,
    dev_url: Option<Url>,
    exiting: AtomicBool,
    smoke: Option<Arc<smoke::Smoke>>,
}

// --- launch configuration -------------------------------------------------------------------

/// Packaged sidecar from the bundle resources, or (development) the repo's Python backend.
fn launch_config<R: Runtime>(app: &AppHandle<R>) -> Result<(Launch, Option<Url>), String> {
    if let Some(python) = std::env::var_os("WESE_DESKTOP_DEV_PYTHON") {
        let backend_dir = PathBuf::from(
            std::env::var_os("WESE_DESKTOP_DEV_BACKEND_DIR")
                .ok_or("WESE_DESKTOP_DEV_BACKEND_DIR")?,
        );
        let dev_url = std::env::var("WESE_DESKTOP_DEV_URL")
            .ok()
            .and_then(|u| Url::parse(&u).ok());
        let web_dir = std::env::var_os("WESE_DESKTOP_DEV_WEB_DIR").map(PathBuf::from);
        return Ok((
            Launch {
                program: PathBuf::from(python),
                args: vec!["-m".into(), "app.desktop".into()],
                cwd: backend_dir.clone(),
                web_dir,
                // with the Vite dev server (HMR) the backend must sit on Vite's proxy port
                fixed_port: dev_url.as_ref().map(|_| 8000),
                extra_env: vec![("PYTHONPATH".into(), backend_dir.display().to_string())],
            },
            dev_url,
        ));
    }
    let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
    let dir = resources.join("backend");
    let exe = if cfg!(windows) {
        "wese-trade-backend.exe"
    } else {
        "wese-trade-backend"
    };
    Ok((
        Launch {
            program: dir.join(exe),
            args: vec![],
            cwd: dir,
            web_dir: None, // the packaged sidecar serves its bundled web/ folder
            fixed_port: None,
            extra_env: vec![],
        },
        None,
    ))
}

fn local_page<R: Runtime>(app: &AppHandle<R>) -> Option<Url> {
    let window = app.get_webview_window(MAIN)?;
    let current = window.url().ok()?;
    let base = if cfg!(any(windows, target_os = "android")) {
        "http://tauri.localhost/index.html"
    } else {
        "tauri://localhost/index.html"
    };
    if current.as_str().starts_with(base) {
        return None; // already on the local page
    }
    Url::parse(base).ok()
}

fn app_url(state: &AppState, port: u16) -> Url {
    state
        .dev_url
        .clone()
        .unwrap_or_else(|| Url::parse(&format!("http://127.0.0.1:{port}/")).expect("valid url"))
}

fn is_local_ui(url: &Url) -> bool {
    match url.scheme() {
        "tauri" => true,
        "http" | "https" => matches!(
            url.host_str(),
            Some("127.0.0.1") | Some("localhost") | Some("tauri.localhost")
        ),
        _ => url.scheme() == "about",
    }
}

fn open_external<R: Runtime>(app: &AppHandle<R>, url: &Url) {
    if matches!(url.scheme(), "http" | "https") && !is_local_ui(url) {
        if let Err(e) = app.opener().open_url(url.as_str(), None::<&str>) {
            log::warn!("could not open external link: {e}");
        }
    }
}

// --- backend start / crash monitor ----------------------------------------------------------

pub(crate) fn start_backend<R: Runtime>(app: AppHandle<R>) {
    std::thread::spawn(move || {
        let state = app.state::<AppState>();
        match state.backend.start() {
            Ok(port) => {
                if let Some(window) = app.get_webview_window(MAIN) {
                    let _ = window.navigate(app_url(&state, port));
                }
                spawn_monitor(app.clone());
                if let Some(smoke) = state.smoke.clone() {
                    if smoke.begin() {
                        smoke::run(app.clone(), smoke, port);
                    } else {
                        smoke.restarted(port);
                    }
                }
            }
            Err(status) => {
                if let Some(smoke) = state.smoke.clone() {
                    smoke.fail(&app, &format!("{status:?}"));
                }
            }
        }
    });
}

fn spawn_monitor<R: Runtime>(app: AppHandle<R>) {
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_millis(500));
        let state = app.state::<AppState>();
        if state.backend.is_stopping() {
            return;
        }
        if let Some(code) = state.backend.poll_exit() {
            if state.backend.is_stopping() {
                return;
            }
            state.backend.mark_crashed(code);
            if let (Some(window), Some(page)) = (app.get_webview_window(MAIN), local_page(&app)) {
                let _ = window.navigate(page); // shows «تعطلت خدمة Wese Trade المحلية»
            }
            return;
        }
    });
}

// --- commands (granted per page in capabilities/) --------------------------------------------

#[tauri::command]
fn startup_status(state: State<'_, AppState>) -> Status {
    state.backend.status()
}

#[tauri::command]
async fn restart_backend<R: Runtime>(app: AppHandle<R>) -> Result<Status, String> {
    let backend = app.state::<AppState>().backend.clone();
    tauri::async_runtime::spawn_blocking(move || {
        backend.stop(STOP_TIMEOUT);
    })
    .await
    .map_err(|e| e.to_string())?;
    start_backend(app.clone());
    Ok(Status::Starting)
}

#[tauri::command]
fn open_data_dir<R: Runtime>(app: AppHandle<R>, state: State<'_, AppState>) -> Result<(), String> {
    app.opener()
        .open_path(state.paths.data().display().to_string(), None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn open_logs_dir<R: Runtime>(app: AppHandle<R>, state: State<'_, AppState>) -> Result<(), String> {
    app.opener()
        .open_path(state.paths.logs().display().to_string(), None::<&str>)
        .map_err(|e| e.to_string())
}

/// Only http(s) links to non-local hosts, opened in the system browser.
#[tauri::command]
fn open_external_url<R: Runtime>(app: AppHandle<R>, url: String) -> Result<(), String> {
    let parsed = Url::parse(&url).map_err(|_| "invalid_url")?;
    if !matches!(parsed.scheme(), "http" | "https") || is_local_ui(&parsed) {
        return Err("not_allowed".into());
    }
    open_external(&app, &parsed);
    Ok(())
}

#[tauri::command]
async fn restart_app<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    let state = app.state::<AppState>();
    let backend = state.backend.clone();
    state.exiting.store(true, Ordering::SeqCst);
    tauri::async_runtime::spawn_blocking(move || backend.stop(STOP_TIMEOUT))
        .await
        .map_err(|e| e.to_string())?;
    app.restart();
}

#[tauri::command]
fn quit_app<R: Runtime>(app: AppHandle<R>) {
    app.exit(0); // goes through the graceful ExitRequested path
}

#[derive(Serialize)]
pub struct UpdateInfo {
    available: bool,
    configured: bool,
    version: Option<String>,
    current_version: String,
    notes: Option<String>,
    date: Option<String>,
}

fn updater_configured<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("pubkey"))
        .and_then(|k| k.as_str())
        .is_some_and(|k| !k.trim().is_empty())
}

#[tauri::command]
async fn check_for_updates<R: Runtime>(app: AppHandle<R>) -> Result<UpdateInfo, String> {
    let current_version = app.package_info().version.to_string();
    if !updater_configured(&app) {
        return Ok(UpdateInfo {
            available: false,
            configured: false,
            version: None,
            current_version,
            notes: None,
            date: None,
        });
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?;
    Ok(match update {
        Some(u) => UpdateInfo {
            available: true,
            configured: true,
            version: Some(u.version.clone()),
            current_version,
            notes: u.body.clone(),
            date: u.date.map(|d| d.to_string()),
        },
        None => UpdateInfo {
            available: false,
            configured: true,
            version: None,
            current_version,
            notes: None,
            date: None,
        },
    })
}

/// Download + verify the signed update FIRST, then stop the backend gracefully (flush,
/// cursors, DB closed), install, and relaunch. The database is never touched.
#[tauri::command]
async fn install_update<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    if !updater_configured(&app) {
        return Err("updates_not_configured".into());
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or("no_update")?;
    let bytes = update
        .download(|_, _| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    let state = app.state::<AppState>();
    state.exiting.store(true, Ordering::SeqCst);
    let backend = state.backend.clone();
    tauri::async_runtime::spawn_blocking(move || backend.stop(STOP_TIMEOUT))
        .await
        .map_err(|e| e.to_string())?;
    update.install(bytes).map_err(|e| e.to_string())?;
    app.restart();
}

#[tauri::command]
fn smoke_report(state: State<'_, AppState>, title: String, text: String) {
    if let Some(smoke) = &state.smoke {
        smoke.record_page(title, text);
    }
}

// --- entry point --------------------------------------------------------------------------

pub fn run() {
    let smoke = smoke::Smoke::from_args().map(Arc::new);
    let paths = match RuntimePaths::resolve()
        .and_then(|p| p.ensure().map(|_| p).map_err(|e| e.to_string()))
    {
        Ok(p) => p,
        Err(e) => {
            eprintln!("Wese Trade: cannot prepare the application data directory: {e}");
            std::process::exit(1);
        }
    };
    let log_dir = paths.logs();

    let app = tauri::Builder::default()
        // must be the first plugin: a second launch only focuses the running window
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window(MAIN) {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(
            tauri_plugin_log::Builder::new()
                .clear_targets()
                .target(Target::new(TargetKind::Folder {
                    path: log_dir,
                    file_name: Some("desktop".into()),
                }))
                .max_file_size(5 * 1024 * 1024)
                .rotation_strategy(RotationStrategy::KeepSome(5))
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            startup_status,
            restart_backend,
            open_data_dir,
            open_logs_dir,
            open_external_url,
            restart_app,
            quit_app,
            check_for_updates,
            install_update,
            smoke_report
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            let (launch, dev_url) = launch_config(&handle)?;
            log::info!(
                "Wese Trade {} starting; data root {:?}",
                handle.package_info().version,
                paths.root
            );
            app.manage(AppState {
                backend: Arc::new(Backend::new(launch, paths.clone())),
                paths: paths.clone(),
                dev_url,
                exiting: AtomicBool::new(false),
                smoke: smoke.clone(),
            });
            let nav_handle = handle.clone();
            let popup_handle = handle.clone();
            WebviewWindowBuilder::new(app, MAIN, WebviewUrl::App("index.html".into()))
                .title("Wese Trade")
                .inner_size(1600.0, 960.0)
                .min_inner_size(1280.0, 720.0)
                .center()
                .on_navigation(move |url| {
                    if is_local_ui(url) {
                        return true;
                    }
                    open_external(&nav_handle, url); // never navigate the app window away
                    false
                })
                .on_new_window(move |url, _features| {
                    open_external(&popup_handle, &url);
                    NewWindowResponse::Deny
                })
                .build()?;
            start_backend(handle);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Wese Trade");

    app.run(|app, event| {
        if let RunEvent::ExitRequested { api, code, .. } = event {
            let state = app.state::<AppState>();
            if state.exiting.swap(true, Ordering::SeqCst)
                && state.backend.status() == Status::Stopped
            {
                return; // shutdown already done: let the process exit
            }
            api.prevent_exit();
            let handle = app.clone();
            std::thread::spawn(move || {
                let state = handle.state::<AppState>();
                let outcome = state.backend.stop(STOP_TIMEOUT);
                log::info!("exiting (backend graceful: {})", outcome.graceful);
                handle.exit(code.unwrap_or(0));
            });
        }
    });
}
