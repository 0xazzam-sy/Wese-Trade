//! Native per-user application-data location (never the installation directory).
//!
//! Windows: `%LOCALAPPDATA%\WeseTrade`, macOS: `~/Library/Application Support/WeseTrade`
//! (resolved with the OS known-folder APIs through the `dirs` crate, the same resolver
//! Tauri's own path API uses). `WESE_RUNTIME_ROOT` overrides it for tests and CI only.

use std::path::PathBuf;

pub const APP_DIR_NAME: &str = "WeseTrade";

#[derive(Clone, Debug)]
pub struct RuntimePaths {
    pub root: PathBuf,
}

impl RuntimePaths {
    pub fn resolve() -> Result<Self, String> {
        if let Some(root) = std::env::var_os("WESE_RUNTIME_ROOT").filter(|v| !v.is_empty()) {
            return Ok(Self {
                root: PathBuf::from(root),
            });
        }
        let base = dirs::data_local_dir().ok_or("no per-user application data directory")?;
        Ok(Self {
            root: base.join(APP_DIR_NAME),
        })
    }

    pub fn data(&self) -> PathBuf {
        self.root.join("data")
    }
    pub fn logs(&self) -> PathBuf {
        self.root.join("logs")
    }
    pub fn database(&self) -> PathBuf {
        self.data().join("wese_trade.db")
    }

    /// Create data/, logs/, cache/, exports/, backups/ (idempotent).
    pub fn ensure(&self) -> std::io::Result<()> {
        for sub in ["data", "logs", "cache", "exports", "backups"] {
            std::fs::create_dir_all(self.root.join(sub))?;
        }
        Ok(())
    }
}
