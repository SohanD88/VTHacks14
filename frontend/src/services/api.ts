import type { ApiErrorResponse, HealthResponse, ScanRequest, ScanResponse } from '../types';

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number, public requestId?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const body = payload as ApiErrorResponse | null;
      throw new ApiError(body?.error?.message || `API request failed (${response.status}).`,
        response.status, body?.error?.request_id);
    }
    if (payload === null) throw new ApiError('The API returned an unreadable response.', response.status);
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new ApiError('The scan request timed out. Check the backend and try again.', 0);
    }
    throw new ApiError('Cannot reach the API. Start the backend, then try again.', 0);
  }
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>('/health', { signal }),
  createScan: (body: ScanRequest, signal?: AbortSignal) => request<ScanResponse>('/scans', {
    method: 'POST', body: JSON.stringify(body), signal,
  }),
  getScan: (id: string, signal?: AbortSignal) => request<ScanResponse>(`/scans/${encodeURIComponent(id)}`, { signal }),
};
