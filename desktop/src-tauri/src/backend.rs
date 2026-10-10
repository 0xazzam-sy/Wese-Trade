//! Lifecycle of the packaged FastAPI sidecar: start on a free loopback port, wait for
//! `/health`, watch for crashes, and stop gracefully (bounded) with a forced fallback.
//!
//! Orphan safety: the sidecar's stdin is a pipe owned by this process. If the shell
//! exits or is killed, the pipe closes and the sidecar shuts itself down.

use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::paths::RuntimePaths;

/// Sidecar exit codes (see backend/app/desktop.py).
pub const EXIT_CONFIG: i32 = 2;
pub const EXIT_MIGRATION: i32 = 3;
pub const EXIT_PORT_IN_USE: i32 = 4;

/// Per attempt. A cold first launch on Windows (PyInstaller unpack + antivirus scan of
/// every DLL) can take minutes; a second attempt is warm, so one timeout is retried.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(150);
const PROGRESS_EVERY: Duration = Duration::from_secs(15);

/// What the splash / crash page shows (polled through `startup_status`).
#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Status {
    Starting,
    Ready { port: u16 },
    Failed { reason: String, code: Option<i32> },
    Crashed { code: Option<i32> },
    Stopping,
    Stopped,
}

/// How to launch the backend: the packaged executable, or the repo's Python in dev mode.
#[derive(Clone, Debug)]
pub struct Launch {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub web_dir: Option<PathBuf>,
    pub fixed_port: Option<u16>,
    pub extra_env: Vec<(String, String)>,
}

#[derive(Debug)]
pub struct StopOutcome {
    pub graceful: bool,
    pub code: Option<i32>,
}

struct Inner {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    port: Option<u16>,
}

pub struct Backend {
    launch: Launch,
    paths: RuntimePaths,
    token: String,
    inner: Mutex<Inner>,
    status: Mutex<Status>,
    stopping: AtomicBool,
}

impl Backend {
    pub fn new(launch: Launch, paths: RuntimePaths) -> Self {
        Self {
            launch,
            paths,
            // fresh per launch; authorises only the local graceful-shutdown call
            token: uuid::Uuid::new_v4().simple().to_string(),
            inner: Mutex::new(Inner {
                child: None,
                stdin: None,
                port: None,
            }),
            status: Mutex::new(Status::Starting),
            stopping: AtomicBool::new(false),
        }
    }

    pub fn status(&self) -> Status {
        self.status.lock().unwrap().clone()
    }

    fn set_status(&self, status: Status) {
        *self.status.lock().unwrap() = status;
    }

    pub fn is_stopping(&self) -> bool {
        self.stopping.load(Ordering::SeqCst)
    }

    /// Start the sidecar and block until `/api/v1/health` answers 200.
    pub fn start(&self) -> Result<u16, Status> {
        self.stopping.store(false, Ordering::SeqCst);
        self.set_status(Status::Starting);
        let mut last_code = None;
        let mut timeouts = 0;
        for attempt in 0..3 {
            let port = match self.launch.fixed_port {
                Some(p) => p,
                None => free_port().map_err(|e| self.fail(format!("port: {e}"), None))?,
            };
            let mut child = self
                .spawn(port)
                .map_err(|e| self.fail(format!("spawn: {e}"), None))?;
            let stdin = child.stdin.take();
            let began = Instant::now();
            let deadline = began + HEALTH_TIMEOUT;
            let mut next_progress = began + PROGRESS_EVERY;
            let mut timed_out = false;
            loop {
                if let Ok(Some(status)) = child.try_wait() {
                    last_code = status.code();
                    log::warn!("backend exited during startup: {:?}", last_code);
                    break;
                }
                if http(port, "GET", "/api/v1/health", &[], None).map(|r| r.status) == Some(200) {
                    let mut inner = self.inner.lock().unwrap();
                    inner.child = Some(child);
                    inner.stdin = stdin;
                    inner.port = Some(port);
                    drop(inner);
                    self.set_status(Status::Ready { port });
                    log::info!("backend ready on 127.0.0.1:{port}");
                    return Ok(port);
                }
                let now = Instant::now();
                if now >= next_progress {
                    // deterministic diagnostics: the process is alive but not serving yet
                    log::info!(
                        "backend still starting (attempt {}, {}s, port {port})",
                        attempt + 1,
                        now.duration_since(began).as_secs()
                    );
                    next_progress = now + PROGRESS_EVERY;
                }
                if now > deadline {
                    log::warn!(
                        "backend health timeout after {}s (attempt {})",
                        HEALTH_TIMEOUT.as_secs(),
                        attempt + 1
                    );
                    let _ = child.kill();
                    let _ = child.wait();
                    timed_out = true;
                    break;
                }
                std::thread::sleep(Duration::from_millis(250));
            }
            if timed_out {
                timeouts += 1;
                if timeouts >= 2 {
                    return Err(self.fail("health_timeout".into(), None));
                }
                continue; // one warm retry after a cold-start timeout
            }
            if last_code != Some(EXIT_PORT_IN_USE) || self.launch.fixed_port.is_some() {
                break; // only a port race is worth retrying
            }
        }
        let reason = match last_code {
            Some(EXIT_MIGRATION) => "migration_failed",
            Some(EXIT_CONFIG) => "config_error",
            Some(EXIT_PORT_IN_USE) => "port_in_use",
            _ => "backend_exited",
        };
        Err(self.fail(reason.into(), last_code))
    }

    fn fail(&self, reason: String, code: Option<i32>) -> Status {
        log::error!("backend start failed: {reason} (code {code:?})");
        let status = Status::Failed { reason, code };
        self.set_status(status.clone());
        status
    }

    fn spawn(&self, port: u16) -> std::io::Result<Child> {
        let stderr = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.paths.logs().join("backend-stderr.log"))?;
        let mut cmd = Command::new(&self.launch.program);
        cmd.args(&self.launch.args)
            .current_dir(&self.launch.cwd)
            .env("WESE_RUNTIME_MODE", "desktop")
            .env("WESE_RUNTIME_ROOT", &self.paths.root)
            .env("WESE_PORT", port.to_string())
            .env("WESE_DESKTOP_TOKEN", &self.token)
            .env("WESE_STDIN_WATCHDOG", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::from(stderr));
        if let Some(web) = &self.launch.web_dir {
            cmd.env("WESE_WEB_DIR", web);
        }
        for (k, v) in &self.launch.extra_env {
            cmd.env(k, v);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        log::info!(
            "starting backend: {:?} on 127.0.0.1:{port}",
            self.launch.program
        );
        cmd.spawn()
    }

    /// Non-blocking crash check used by the monitor thread.
    pub fn poll_exit(&self) -> Option<Option<i32>> {
        let mut inner = self.inner.lock().unwrap();
        let child = inner.child.as_mut()?;
        match child.try_wait() {
            Ok(Some(status)) => {
                inner.child = None;
                inner.stdin = None;
                inner.port = None;
                Some(status.code())
            }
            _ => None,
        }
    }

    /// Smoke test only: terminate the sidecar abruptly, exactly like a crash.
    pub fn simulate_crash(&self) {
        if let Some(child) = self.inner.lock().unwrap().child.as_mut() {
            let _ = child.kill();
        }
    }

    pub fn mark_crashed(&self, code: Option<i32>) {
        log::error!("backend crashed (exit code {code:?})");
        self.set_status(Status::Crashed { code });
    }

    /// Graceful stop: flush + close via the shutdown hook, bounded wait, then force.
    pub fn stop(&self, timeout: Duration) -> StopOutcome {
        self.stopping.store(true, Ordering::SeqCst);
        self.set_status(Status::Stopping);
        let (port, mut child, stdin) = {
            let mut inner = self.inner.lock().unwrap();
            (inner.port.take(), inner.child.take(), inner.stdin.take())
        };
        let Some(child_ref) = child.as_mut() else {
            self.set_status(Status::Stopped);
            return StopOutcome {
                graceful: true,
                code: None,
            };
        };
        if let Some(port) = port {
            let header = ("X-Wese-Desktop-Token", self.token.as_str());
            let _ = http(port, "POST", "/api/v1/system/shutdown", &[header], None);
        }
        drop(stdin); // closing the pipe is a second, independent stop signal
        let deadline = Instant::now() + timeout;
        let outcome = loop {
            match child_ref.try_wait() {
                Ok(Some(status)) => {
                    break StopOutcome {
                        graceful: true,
                        code: status.code(),
                    }
                }
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(100))
                }
                _ => {
                    log::warn!("backend did not stop within {timeout:?}: forcing termination");
                    let _ = child_ref.kill();
                    let code = child_ref.wait().ok().and_then(|s| s.code());
                    break StopOutcome {
                        graceful: false,
                        code,
                    };
                }
            }
        };
        log::info!("backend stopped: {outcome:?}");
        self.set_status(Status::Stopped);
        outcome
    }
}

pub fn free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind(SocketAddr::from((Ipv4Addr::LOCALHOST, 0)))?;
    Ok(listener.local_addr()?.port())
}

pub struct HttpResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: String,
}

/// Minimal HTTP/1.0 client for loopback calls only (no external dependency).
pub fn http(
    port: u16,
    method: &str,
    path: &str,
    headers: &[(&str, &str)],
    body: Option<&str>,
) -> Option<HttpResponse> {
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_secs(1)).ok()?;
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .ok()?;
    let payload = body.unwrap_or("");
    let mut request = format!("{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n");
    for (name, value) in headers {
        request.push_str(&format!("{name}: {value}\r\n"));
    }
    if body.is_some() {
        request.push_str("Content-Type: application/json\r\n");
    }
    request.push_str(&format!(
        "Content-Length: {}\r\n\r\n{payload}",
        payload.len()
    ));
    stream.write_all(request.as_bytes()).ok()?;
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).ok()?;
    let text = String::from_utf8_lossy(&raw).into_owned();
    let (head, body) = text.split_once("\r\n\r\n").unwrap_or((text.as_str(), ""));
    let mut lines = head.lines();
    let status = lines.next()?.split_whitespace().nth(1)?.parse().ok()?;
    let headers = lines
        .filter_map(|l| l.split_once(':'))
        .map(|(k, v)| (k.trim().to_ascii_lowercase(), v.trim().to_string()))
        .collect();
    Some(HttpResponse {
        status,
        headers,
        body: body.to_string(),
    })
}
