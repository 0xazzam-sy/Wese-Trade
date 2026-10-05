fn main() {
    // Every app command is declared here so Tauri generates `allow-<command>` permissions;
    // pages only get the ones their capability file grants.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "startup_status",
            "restart_backend",
            "open_data_dir",
            "open_logs_dir",
            "open_external_url",
            "restart_app",
            "quit_app",
            "check_for_updates",
            "install_update",
            "smoke_report",
        ]),
    ))
    .expect("failed to run tauri-build");
}
