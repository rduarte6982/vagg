import axios, { type AxiosError } from 'axios';

/**
 * vagg-portal API client (SPEC §5.6 / Fase 11).
 *
 * Auth uses an httpOnly cookie set by GET /portal/auth/consume — there is
 * no JWT in localStorage here on purpose: the portal is read-only public
 * surface and we minimize what's accessible to JS.
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

export const Portal = {
  requestMagicLink: async (email: string, client_id: string): Promise<void> => {
    await api.post('/auth/request_magic_link', { email, client_id });
  },
  consume: async (token: string): Promise<{ requires_totp: boolean; viewer_email: string; client_id: string }> =>
    (await api.get('/auth/consume', { params: { token } })).data,
  postTotp: async (code: string): Promise<void> => {
    await api.post('/auth/totp', { code });
  },
  dashboard: async (): Promise<Record<string, unknown>> => (await api.get('/dashboard')).data,
  timeline: async (limit = 100): Promise<Array<Record<string, unknown>>> =>
    (await api.get('/timeline', { params: { limit } })).data,
  reportsLgpd: async (): Promise<Blob> =>
    (await api.post('/reports/lgpd', null, { responseType: 'blob' })).data as Blob,
};
