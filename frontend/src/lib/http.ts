import { apiBaseUrl } from './env';

/** Error thrown for non-2xx API responses or network failures. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfterSeconds: number | null;

  constructor(status: number, code: string, retryAfterSeconds: number | null = null) {
    super(`API error ${status}: ${code}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

/** Subscribe to 401 responses from authenticated endpoints (session expired/revoked). */
export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  /** When false, a 401 does not notify session listeners (e.g. the login call itself). */
  notifyUnauthorized?: boolean;
}

async function readErrorCode(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === 'string' ? payload.detail : 'request_failed';
  } catch {
    return 'request_failed';
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, notifyUnauthorized = true } = options;
  const init: RequestInit = {
    method,
    credentials: 'include',
    headers:
      body === undefined
        ? { Accept: 'application/json' }
        : {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  if (signal) init.signal = signal;

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, 'network_error');
  }

  if (!response.ok) {
    const retryAfter = Number(response.headers.get('Retry-After'));
    const apiError = new ApiError(
      response.status,
      await readErrorCode(response),
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
    );
    if (response.status === 401 && notifyUnauthorized) {
      unauthorizedListeners.forEach((listener) => {
        listener();
      });
    }
    throw apiError;
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
