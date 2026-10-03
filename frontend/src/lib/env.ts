/** Browser-safe runtime configuration (never contains secrets). */

function trimTrailingSlash(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

export const apiBaseUrl = trimTrailingSlash(import.meta.env.VITE_API_BASE_URL ?? '/api/v1');

/** Resolve the WebSocket URL, deriving it from the page origin when not configured. */
export function resolveWsUrl(location: Pick<Location, 'protocol' | 'host'> = window.location) {
  const configured = import.meta.env.VITE_WS_BASE_URL;
  if (configured) return `${trimTrailingSlash(configured)}/ws`;

  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
  if (/^https?:\/\//.test(apiBaseUrl)) {
    return `${apiBaseUrl.replace(/^http/, 'ws')}/ws`;
  }
  return `${scheme}//${location.host}${apiBaseUrl}/ws`;
}
