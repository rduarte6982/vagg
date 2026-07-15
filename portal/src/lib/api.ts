import axios, { type AxiosError } from 'axios';
import { isDemo, PortalDemo } from './demo';

/**
 * vagg-portal API client (SPEC §5.6 / Fase 11).
 *
 * Auth uses an httpOnly cookie set by GET /portal/auth/consume — there is
 * no JWT in localStorage here on purpose: the portal is read-only public
 * surface and we minimize what's accessible to JS.
 *
 * Quando `isDemo()` é verdadeiro, todas as chamadas usam o conjunto de
 * dados em memória de `lib/demo.ts` ao invés de bater no /portal real —
 * útil para apresentações sem backend.
 */

export const api = axios.create({
  baseURL: '/portal',
  withCredentials: true,
  timeout: 15_000,
});

api.interceptors.response.use(
  (r) => r,
  (err: AxiosError) => {
    const body = err.response?.data as { detail?: string } | undefined;
    return Promise.reject(new Error(body?.detail ?? err.message));
  },
);

async function delay<T>(value: T, ms = 150): Promise<T> {
  await new Promise((r) => setTimeout(r, ms));
  return value;
}

export const Portal = {
  requestMagicLink: async (email: string, client_id: string): Promise<void> => {
    if (isDemo()) {
      PortalDemo.requestMagicLink(email, client_id);
      await delay(undefined, 250);
      return;
    }
    await api.post('/auth/request_magic_link', { email, client_id });
  },
  consume: async (
    token: string,
  ): Promise<{ requires_totp: boolean; viewer_email: string; client_id: string }> => {
    if (isDemo()) return delay(PortalDemo.consume(token));
    return (await api.get('/auth/consume', { params: { token } })).data;
  },
  postTotp: async (code: string): Promise<void> => {
    if (isDemo()) {
      PortalDemo.postTotp(code);
      await delay(undefined);
      return;
    }
    await api.post('/auth/totp', { code });
  },
  dashboard: async (): Promise<Record<string, unknown>> => {
    if (isDemo()) return delay(PortalDemo.dashboard());
    return (await api.get('/dashboard')).data;
  },
  timeline: async (limit = 100): Promise<Array<Record<string, unknown>>> => {
    if (isDemo()) return delay(PortalDemo.timeline().slice(0, limit));
    return (await api.get('/timeline', { params: { limit } })).data;
  },
  reportsLgpd: async (): Promise<Blob> => {
    if (isDemo()) return delay(PortalDemo.reportsLgpd(), 320);
    return (await api.post('/reports/lgpd', null, { responseType: 'blob' })).data as Blob;
  },
};
