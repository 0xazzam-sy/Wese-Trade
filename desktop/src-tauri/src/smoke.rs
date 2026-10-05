//! `--smoke-test <report.json>`: automated end-to-end check used by CI on Windows and
//! macOS (and locally). It launches the real app, waits for the packaged backend, checks
//! the API through loopback, confirms the React UI rendered inside the webview, stops the
//! backend gracefully and writes a JSON report. No production behaviour depends on it.
//!
//! `WESE_SMOKE_SETUP=1` also creates the first admin (first launch) or logs in with it
//! (later launches) so persistence across launches can be verified.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager, Runtime};

use crate::backend::{http, Status};
use crate::{start_backend, AppState, MAIN};

const USER: &str = "smoke-admin";
const PASSWORD: &str = "Smoke-Test-Pass-2026";

pub struct Smoke {
    report: PathBuf,
    started: Instant,
    page: Mutex<Option<(String, String)>>,
    begun: AtomicBool,
    restarted_port: Mutex<Option<u16>>,
}

impl Smoke {
    pub fn from_args() -> Option<Self> {
        let args: Vec<String> = std::env::args().collect();
        let i = args.iter().position(|a| a == "--smoke-test")?;
        Some(Self {
            report: PathBuf::from(args.get(i + 1)?),
            started: Instant::now(),
            page: Mutex::new(None),
            begun: AtomicBool::new(false),
            restarted_port: Mutex::new(None),
        })
    }

    /// True only for the first backend start of this launch.
    pub fn begin(&self) -> bool {
        !self.begun.swap(true, Ordering::SeqCst)
    }

    pub fn restarted(&self, port: u16) {
        *self.restarted_port.lock().unwrap() = Some(port);
    }

    pub fn record_page(&self, title: String, text: String) {
        *self.page.lock().unwrap() = Some((title, text));
    }

    pub fn fail<R: Runtime>(&self, app: &AppHandle<R>, reason: &str) {
        self.write(&json!({ "ok": false, "error": reason }));
        app.exit(1);
    }

    fn write(&self, value: &Value) {
        let text = serde_json::to_string_pretty(value).unwrap_or_default();
        if let Err(e) = std::fs::write(&self.report, text) {
            eprintln!("smoke: cannot write report: {e}");
        }
    }
}

fn json_body(raw: &str) -> Value {
    serde_json::from_str(raw).unwrap_or(Value::Null)
}

pub fn run<R: Runtime>(app: AppHandle<R>, smoke: Arc<Smoke>, port: u16) {
    std::thread::spawn(move || {
        let state = app.state::<AppState>();
        let health = http(port, "GET", "/api/v1/health", &[], None);
        let setup = http(port, "GET", "/api/v1/auth/setup", &[], None);
        let needs_setup = setup
            .as_ref()
            .map(|r| json_body(&r.body)["needs_setup"].clone());

        // optional: account persistence across launches
        let mut account = Value::Null;
        let mut forward = Value::Null;
        let mut runtime = Value::Null;
        if std::env::var("WESE_SMOKE_SETUP").as_deref() == Ok("1") {
            let creds = json!({ "username": USER, "password": PASSWORD }).to_string();
            let first = needs_setup
                .as_ref()
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let path = if first {
                "/api/v1/auth/setup"
            } else {
                "/api/v1/auth/login"
            };
            if let Some(resp) = http(port, "POST", path, &[], Some(&creds)) {
                let cookie = resp
                    .headers
                    .iter()
                    .find(|(k, _)| k == "set-cookie")
                    .and_then(|(_, v)| v.split(';').next())
                    .map(str::to_string)
                    .unwrap_or_default();
                account = json!({ "action": path, "status": resp.status });
                let headers = [("Cookie", cookie.as_str())];
                if let Some(r) = http(port, "GET", "/api/v1/forward-test/status", &headers, None) {
                    forward = json_body(&r.body)["run"].clone();
                }
                if let Some(r) = http(port, "GET", "/api/v1/system/runtime", &headers, None) {
                    runtime = json_body(&r.body);
                }
            }
        }

        // the React app must actually render inside the webview (re-injected until it
        // reports, because a navigation in progress discards injected scripts)
        let probe = "(function poll(n){var r=document.querySelector('#root');\
             if(r&&r.children.length&&r.innerText.trim().length){\
             window.__TAURI_INTERNALS__.invoke('smoke_report',{title:document.title,\
             text:r.innerText.slice(0,200)});}else if(n>0){setTimeout(function(){poll(n-1)},250);}})(8);";
        let deadline = Instant::now() + Duration::from_secs(60);
        while smoke.page.lock().unwrap().is_none() && Instant::now() < deadline {
            if let Some(window) = app.get_webview_window(MAIN) {
                let _ = window.eval(probe);
            }
            std::thread::sleep(Duration::from_millis(2000));
        }
        let page = smoke.page.lock().unwrap().clone();
        let window_url = app
            .get_webview_window(MAIN)
            .and_then(|w| w.url().ok())
            .map(|u| u.to_string());

        // optional: crash -> detected by the monitor -> crash page -> service restart
        let mut crash = Value::Null;
        if std::env::var("WESE_SMOKE_CRASH").as_deref() == Ok("1") {
            state.backend.simulate_crash();
            let detected = wait_for(Duration::from_secs(10), || {
                matches!(state.backend.status(), Status::Crashed { .. })
            });
            let crash_page = app
                .get_webview_window(MAIN)
                .and_then(|w| w.url().ok())
                .map(|u| u.to_string());
            start_backend(app.clone()); // what the «إعادة تشغيل الخدمة» button does
            let recovered = wait_for(Duration::from_secs(60), || {
                smoke.restarted_port.lock().unwrap().is_some()
            });
            let new_port = *smoke.restarted_port.lock().unwrap();
            let healthy = new_port
                .and_then(|p| http(p, "GET", "/api/v1/health", &[], None))
                .map(|r| r.status)
                == Some(200);
            crash = json!({
                "detected": detected,
                "crash_page": crash_page,
                "recovered": recovered && healthy,
                "new_port": new_port,
            });
        }

        let stop = state.backend.stop(Duration::from_secs(20));
        let db = state.paths.database();
        let crash_ok = crash.is_null() || crash["recovered"] == json!(true);
        let ok = health.as_ref().map(|r| r.status) == Some(200)
            && page.is_some()
            && stop.graceful
            && db.exists()
            && crash_ok;
        smoke.write(&json!({
            "ok": ok,
            "app_version": app.package_info().version.to_string(),
            "port": port,
            "root": state.paths.root,
            "database_exists": db.exists(),
            "health": health.map(|r| json_body(&r.body)),
            "needs_setup_at_start": needs_setup,
            "account": account,
            "forward_run": forward,
            "runtime": runtime,
            "page": page.map(|(t, x)| json!({ "title": t, "text": x })),
            "window_url": window_url,
            "crash_recovery": crash,
            "backend_stopped_gracefully": stop.graceful,
            "backend_exit_code": stop.code,
            "elapsed_ms": smoke.started.elapsed().as_millis() as u64,
        }));
        app.exit(if ok { 0 } else { 1 });
    });
}

fn wait_for(timeout: Duration, mut done: impl FnMut() -> bool) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if done() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    done()
}
