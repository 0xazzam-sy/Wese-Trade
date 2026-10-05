import { invoke, isTauri } from '@tauri-apps/api/core';

/**
 * Bridge to the Wese Trade desktop shell (Tauri). Every call is a fixed, named command
 * implemented in Rust (no shell access, no arbitrary paths). In the browser these are
 * unavailable and the UI hides the related controls.
 */

export interface UpdateInfo {
  available: boolean;
  configured: boolean;
  version: string | null;
  current_version: string;
  notes: string | null;
  date: string | null;
}

export function isDesktop(): boolean {
  try {
    return isTauri();
  } catch {
    return false;
  }
}

export const desktop = {
  openDataFolder: () => invoke<undefined>('open_data_dir'),
  openLogsFolder: () => invoke<undefined>('open_logs_dir'),
  checkForUpdates: () => invoke<UpdateInfo>('check_for_updates'),
  /** Downloads + verifies the signed update, stops the backend gracefully, then relaunches. */
  installUpdate: () => invoke<undefined>('install_update'),
};
