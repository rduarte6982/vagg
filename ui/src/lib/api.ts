import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';
import { Demo, isDemo } from './demo';

/**
 * Wraps the FastAPI core (SPEC §5.1). The axios client lives at module scope so
 * a single interceptor adds the bearer token to every outbound request and a
 * second interceptor unwraps `vagg-core`'s domain errors into `ApiError`.
 *
 * Quando `isDemo()` retorna verdadeiro (?demo=1 ou VITE_DEMO=true), todos os
 * endpoints abaixo usam a base de dados em memória de `lib/demo.ts` ao invés
 * de chamar o backend — usado para visitas-guiadas e screenshots.
 */

const STORAGE_TOKEN = 'vagg.access_token';
const STORAGE_REFRESH = 'vagg.refresh_token';

export class ApiError extends Error {
  status: number;
  code: string;
  detail: string;
  context?: Record<string, unknown>;

  constructor(status: number, code: string, detail: string, context?: Record<string, unknown>) {
    super(detail || code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.context = context;
  }
}

export function getAccessToken(): string | null {
  return localStorage.getItem(STORAGE_TOKEN);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(STORAGE_REFRESH);
}

export function setTokens(access: string, refresh: string | null): void {
  localStorage.setItem(STORAGE_TOKEN, access);
  if (refresh !== null) {
    localStorage.setItem(STORAGE_REFRESH, refresh);
  }
}

export function clearTokens(): void {
  localStorage.removeItem(STORAGE_TOKEN);
  localStorage.removeItem(STORAGE_REFRESH);
}

function attachAuth(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const token = getAccessToken();
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  return config;
}

function unwrapError(err: AxiosError): never {
  if (err.response) {
    const body = err.response.data as
      | { code?: string; detail?: string; context?: Record<string, unknown> }
      | undefined;
    throw new ApiError(
      err.response.status,
      body?.code ?? 'UNKNOWN',
      body?.detail ?? err.message,
      body?.context,
    );
  }
  throw new ApiError(0, 'NETWORK', err.message);
}

function makeClient(): AxiosInstance {
  const inst = axios.create({
    baseURL: '/api/v1',
    headers: { 'Content-Type': 'application/json' },
    timeout: 30_000,
  });
  inst.interceptors.request.use(attachAuth);

  // Auto-refresh em 401: tenta refresh_token uma vez, retry a request original.
  // Sem isso, todo background polling morre após o JWT expirar (~15min).
  let refreshing: Promise<string | null> | null = null;
  async function refreshNow(): Promise<string | null> {
    const rt = getRefreshToken();
    if (!rt) return null;
    try {
      const resp = await axios.post(
        '/api/v1/auth/refresh',
        { refresh_token: rt },
        { headers: { 'Content-Type': 'application/json' }, timeout: 15_000 },
      );
      const newAccess = resp.data?.access_token as string | undefined;
      if (newAccess) {
        setTokens(newAccess, rt);
        return newAccess;
      }
    } catch {
      /* fall through */
    }
    return null;
  }

  inst.interceptors.response.use(
    (resp) => resp,
    async (err: AxiosError) => {
      // 401 + tem refresh + ainda não retentou → refresh + retry
      const cfg = err.config as InternalAxiosRequestConfig & { _vagg_retried?: boolean };
      if (
        err.response?.status === 401 &&
        cfg &&
        !cfg._vagg_retried &&
        getRefreshToken()
      ) {
        cfg._vagg_retried = true;
        refreshing = refreshing ?? refreshNow();
        const newTok = await refreshing;
        refreshing = null;
        if (newTok) {
          cfg.headers?.set?.('Authorization', `Bearer ${newTok}`);
          try {
            return await inst.request(cfg);
          } catch (retryErr) {
            return unwrapError(retryErr as AxiosError);
          }
        }
        // refresh falhou — limpa estado pra forçar re-login
        clearTokens();
      }
      return unwrapError(err);
    },
  );
  return inst;
}

export const api = makeClient();

// pequeno wrapper que adiciona delay artificial para o modo demo (deixa
// transições visualmente perceptíveis: spinners aparecem, polling alterna).
// 40ms é curto o bastante pra não chamar atenção mas suficiente pra micro-task
// do React render finalizar antes do "data" aparecer.
async function demoDelay<T>(value: T, ms = 40): Promise<T> {
  await new Promise((r) => setTimeout(r, ms));
  return value;
}

// ----- Domain types (mirror vagg-core schemas) -----

export type VpnType =
  | 'openvpn'
  | 'openconnect'
  | 'openfortivpn'
  | 'wireguard'
  | 'strongswan'
  | 'globalprotect';
export type TunnelState = 'stopped' | 'starting' | 'up' | 'down' | 'errored';

export interface NatMapping {
  virtual_cidr: string;
  real_cidr: string;
  description?: string | null;
}

export interface Client {
  id: string;
  name: string;
  vpn_type: VpnType;
  virtual_cidr: string;
  real_cidr: string;
  dns_server?: string | null;
  description?: string | null;
  nat_mappings: NatMapping[];
  tunnel_state: TunnelState;
  tunnel_last_error?: string | null;
  tunnel_last_check_at?: string | null;
  requires_otp?: boolean;
  auth_method?: 'none' | 'otp' | 'saml';
  has_saml_cookie?: boolean;
  has_totp_secret?: boolean;
  has_config?: boolean;
  has_credentials?: boolean;
  saml_cookie_expires_at?: string | null;
  saml_cookie?: string | null; // só pra UPDATE (PATCH); GET nunca devolve

  created_at: string;
  updated_at: string;
}

export interface Consultant {
  id: number;
  email: string;
  name: string;
  has_password?: boolean;
  openvpn_username?: string | null;
  static_pool_ip?: string | null;
  role: 'viewer' | 'operator' | 'admin';
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConsultantCreatePayload extends Partial<Consultant> {
  password?: string;
}

export interface Policy {
  id: number;
  consultant_id: number;
  client_id: string;
  scope_kind: 'full' | 'subnet' | 'host';
  scope_value?: string | null;
  expires_at?: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  actor_consultant_id?: number | null;
  payload?: Record<string, unknown> | null;
  prev_hash?: string | null;
  hash: string;
  occurred_at: string;
}

export interface TunnelStatusReport {
  state: TunnelState;
  container_id?: string | null;
  controller_state?: string | null;
  uptime_s?: number | null;
  error?: string | null;
}

// ----- Endpoints -----

export const Auth = {
  async login(email: string, password: string): Promise<{ access_token: string; refresh_token: string }> {
    if (isDemo()) return demoDelay(Demo.login(email, password), 320);
    const params = new URLSearchParams();
    params.set('username', email);
    params.set('password', password);
    const resp = await api.post('/auth/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return resp.data;
  },
  async refresh(refresh_token: string): Promise<{ access_token: string }> {
    if (isDemo()) return demoDelay({ access_token: 'demo.access.token' });
    const resp = await api.post('/auth/refresh', { refresh_token });
    return resp.data;
  },
  async me(): Promise<{ email: string; role: string }> {
    if (isDemo()) return demoDelay(Demo.me(), 80);
    const resp = await api.get('/auth/me');
    return resp.data;
  },
};

export interface ClientConfigSnapshot {
  config_text: string | null;
  vpn_username: string | null;
}

export const Clients = {
  list: async (): Promise<Client[]> =>
    isDemo() ? demoDelay(Demo.listClients() as Client[]) : (await api.get('/clients')).data,
  get: async (id: string): Promise<Client> =>
    isDemo()
      ? demoDelay(Demo.listClients().find((c) => c.id === id) as Client)
      : (await api.get(`/clients/${id}`)).data,
  getConfig: async (id: string): Promise<ClientConfigSnapshot> => {
    if (isDemo()) {
      return demoDelay({ config_text: '(demo · sem config real)', vpn_username: 'demo' });
    }
    return (await api.get(`/clients/${id}/config`)).data;
  },
  create: async (body: Partial<Client>): Promise<Client> =>
    isDemo()
      ? demoDelay(Demo.createClient(body) as Client)
      : (await api.post('/clients', body)).data,
  update: async (id: string, body: Partial<Client>): Promise<Client> => {
    if (isDemo()) {
      // demo update é raso — apenas devolve o estado atual
      return demoDelay(Demo.listClients().find((c) => c.id === id) as Client);
    }
    return (await api.patch(`/clients/${id}`, body)).data;
  },
  remove: async (id: string): Promise<void> => {
    if (isDemo()) {
      Demo.removeClient(id);
      await demoDelay(undefined);
      return;
    }
    await api.delete(`/clients/${id}`);
  },
};

export const Tunnels = {
  status: async (clientId: string): Promise<TunnelStatusReport> => {
    if (isDemo()) {
      const c = Demo.listClients().find((x) => x.id === clientId);
      return demoDelay({ state: c?.tunnel_state ?? 'stopped' } as TunnelStatusReport);
    }
    return (await api.get(`/clients/${clientId}/status`)).data;
  },
  connect: async (clientId: string): Promise<TunnelStatusReport> => {
    if (isDemo()) return demoDelay(Demo.connectTunnel(clientId) as TunnelStatusReport, 280);
    return (await api.post(`/clients/${clientId}/connect`)).data;
  },
  disconnect: async (clientId: string): Promise<void> => {
    if (isDemo()) {
      Demo.disconnectTunnel(clientId);
      await demoDelay(undefined);
      return;
    }
    await api.post(`/clients/${clientId}/disconnect`);
  },
  sendOtp: async (clientId: string, code: string): Promise<void> => {
    if (isDemo()) {
      await demoDelay(undefined);
      return;
    }
    await api.post(`/clients/${clientId}/otp`, { code });
  },
  logs: async (clientId: string, lines = 100): Promise<{ lines: string[] }> => {
    if (isDemo()) {
      return demoDelay({
        lines: [
          `[demo] cliente=${clientId}`,
          '[demo] modo demonstração ativo · logs reais ficam em /var/log/vagg',
        ].slice(0, lines),
      });
    }
    return (await api.get(`/clients/${clientId}/logs`, { params: { lines } })).data;
  },
};

// ----- SAML SSO (cookie capture via browser remoto) -----

export interface SamlStartResponse {
  portal_url: string;
  expires_at: string;
  container_id: string;
}

export interface SamlPollResponse {
  captured: boolean;
  cookie_expires_at?: string | null;
  error?: string | null;
}

export interface SamlPreloginResponse {
  idp_url: string;
  method: string;
  gateway_host: string;
  cookie_capture_hint: string;
}

export const Saml = {
  prelogin: async (clientId: string): Promise<SamlPreloginResponse> => {
    if (isDemo()) {
      return demoDelay({
        idp_url: 'https://login.microsoftonline.com/...',
        method: 'REDIRECT',
        gateway_host: 'demo.example.com',
        cookie_capture_hint: 'demo mode',
      });
    }
    return (await api.post(`/clients/${clientId}/saml/prelogin`)).data;
  },
  start: async (clientId: string, gatewayUrl?: string): Promise<SamlStartResponse> => {
    if (isDemo()) {
      return demoDelay({
        portal_url: 'about:blank',
        expires_at: new Date(Date.now() + 1200_000).toISOString(),
        container_id: 'demo-saml',
      });
    }
    // Timeout maior — backend espera o container saml-portal subir + noVNC
    // pronto, o que pode levar até 60s. Default axios 30s é insuficiente.
    return (
      await api.post(
        `/clients/${clientId}/saml/start`,
        { gateway_url: gatewayUrl },
        { timeout: 90_000 },
      )
    ).data;
  },
  poll: async (clientId: string): Promise<SamlPollResponse> => {
    if (isDemo()) return demoDelay({ captured: false });
    return (await api.get(`/clients/${clientId}/saml/poll`)).data;
  },
  clearCookie: async (clientId: string): Promise<void> => {
    if (isDemo()) {
      await demoDelay(undefined);
      return;
    }
    await api.delete(`/clients/${clientId}/saml/cookie`);
  },
  stopPortal: async (clientId: string): Promise<void> => {
    if (isDemo()) {
      await demoDelay(undefined);
      return;
    }
    await api.post(`/clients/${clientId}/saml/stop`);
  },
  pasteCookie: async (
    clientId: string,
    cookie: string,
  ): Promise<{
    client_id: string;
    cookie_name: string;
    cookie_value_len: number;
    expires_at: string;
    detected_format: string;
  }> => {
    if (isDemo()) {
      return demoDelay({
        client_id: clientId,
        cookie_name: 'SVPNCOOKIE',
        cookie_value_len: cookie.length,
        expires_at: new Date(Date.now() + 43_200_000).toISOString(),
        detected_format: 'demo',
      });
    }
    return (
      await api.post(`/clients/${clientId}/saml/cookie`, { cookie })
    ).data;
  },
  seenCookies: async (
    clientId: string,
  ): Promise<{
    client_id: string;
    entries: Array<{
      ts: string;
      host: string;
      path: string;
      cookies: Array<{ name: string; value_len: number; value_prefix: string; in_watchlist: boolean }>;
    }>;
    hint: string;
  }> => {
    if (isDemo()) {
      return demoDelay({
        client_id: clientId,
        entries: [],
        hint: 'demo mode — log vazio',
      });
    }
    return (await api.get(`/clients/${clientId}/saml/seen-cookies`)).data;
  },

  // ----- SAML-LOGIN MODE (openfortivpn --saml-login=PORT) -----
  // Caminho NOVO pra FortiGate Vexia/hostcheck. User loga no browser
  // dele, o gateway redireciona pra http://127.0.0.1:PORT/?id=X, frontend
  // captura URL e posta `id` aqui → openfortivpn pega cookie na mesma
  // TLS session (sem invalidação por pinning).
  startLogin: async (
    clientId: string,
  ): Promise<{
    client_id: string;
    vpn_type: string;
    start_url: string;
    port: number;
    expected_callback_prefix: string;
    container_id: string | null;
    portal_url?: string | null;
    gateway_host: string;
  }> => {
    if (isDemo()) {
      return demoDelay({
        client_id: clientId,
        vpn_type: 'openfortivpn',
        start_url: 'about:blank',
        port: 8020,
        expected_callback_prefix: 'http://127.0.0.1:8020/?id=',
        container_id: 'demo-saml-login',
        portal_url: null,
        gateway_host: 'demo.example.com',
      });
    }
    return (
      await api.post(`/clients/${clientId}/saml-login/start`, undefined, {
        timeout: 60_000,
      })
    ).data;
  },
  relayLogin: async (
    clientId: string,
    samlId: string,
  ): Promise<{ client_id: string; relayed: boolean; status_code: number }> => {
    if (isDemo()) {
      return demoDelay({ client_id: clientId, relayed: true, status_code: 200 });
    }
    return (
      await api.post(
        `/clients/${clientId}/saml-login/relay`,
        { saml_id: samlId },
        { timeout: 30_000 },
      )
    ).data;
  },
};

// ----- TOTP / Auto-OTP (seed RFC 6238 cifrado at-rest) -----

export interface TotpInfo {
  has_secret: boolean;
  issuer?: string | null;
  account?: string | null;
  digits?: number;
  period?: number;
  algorithm?: string;
  seconds_remaining?: number | null;
}

export interface TotpPreview {
  code: string;
  seconds_remaining: number;
  period: number;
}

export const Totp = {
  get: async (clientId: string): Promise<TotpInfo> => {
    if (isDemo()) return demoDelay({ has_secret: false });
    return (await api.get(`/clients/${clientId}/totp`)).data;
  },
  set: async (clientId: string, secret: string): Promise<TotpInfo> => {
    if (isDemo()) {
      return demoDelay({
        has_secret: true,
        digits: 6,
        period: 30,
        algorithm: 'sha1',
        seconds_remaining: 30,
      });
    }
    return (await api.put(`/clients/${clientId}/totp`, { secret })).data;
  },
  remove: async (clientId: string): Promise<void> => {
    if (isDemo()) {
      await demoDelay(undefined);
      return;
    }
    await api.delete(`/clients/${clientId}/totp`);
  },
  preview: async (clientId: string): Promise<TotpPreview> => {
    if (isDemo()) {
      return demoDelay({
        code: '123456',
        seconds_remaining: 17,
        period: 30,
      });
    }
    return (await api.post(`/clients/${clientId}/totp/preview`)).data;
  },
};

export const Consultants = {
  list: async (): Promise<Consultant[]> =>
    isDemo() ? demoDelay(Demo.listConsultants() as Consultant[]) : (await api.get('/consultants')).data,
  create: async (body: ConsultantCreatePayload): Promise<Consultant> =>
    isDemo()
      ? demoDelay(Demo.createConsultant(body) as Consultant)
      : (await api.post('/consultants', body)).data,
  update: async (id: number, body: Partial<Consultant>): Promise<Consultant> => {
    if (isDemo()) {
      const updated = Demo.updateConsultant(id, body);
      return demoDelay(updated as Consultant);
    }
    return (await api.patch(`/consultants/${id}`, body)).data;
  },
  setPassword: async (id: number, password: string): Promise<Consultant> => {
    if (isDemo()) {
      const updated = Demo.setConsultantPassword(id);
      // password é só pra ter shape compatível; nada é guardado em demo.
      void password;
      return demoDelay(updated as Consultant);
    }
    return (await api.put(`/consultants/${id}/password`, { password })).data;
  },
  remove: async (id: number): Promise<void> => {
    if (isDemo()) {
      Demo.removeConsultant(id);
      await demoDelay(undefined);
      return;
    }
    await api.delete(`/consultants/${id}`);
  },
};

export const Policies = {
  list: async (): Promise<Policy[]> =>
    isDemo() ? demoDelay(Demo.listPolicies() as Policy[]) : (await api.get('/policies')).data,
  create: async (body: Partial<Policy>): Promise<Policy> =>
    isDemo()
      ? demoDelay(Demo.createPolicy(body) as Policy)
      : (await api.post('/policies', body)).data,
  remove: async (id: number): Promise<void> => {
    if (isDemo()) {
      Demo.removePolicy(id);
      await demoDelay(undefined);
      return;
    }
    await api.delete(`/policies/${id}`);
  },
};

export const Audit = {
  list: async (params?: {
    event_type?: string;
    consultant_id?: number;
    since?: string;
    until?: string;
    limit?: number;
  }): Promise<AuditEvent[]> => {
    if (isDemo()) {
      let evts = Demo.listAudit();
      if (params?.event_type) {
        evts = evts.filter((e) => e.event_type.includes(params.event_type ?? ''));
      }
      if (params?.consultant_id) {
        evts = evts.filter((e) => e.actor_consultant_id === params.consultant_id);
      }
      return demoDelay(evts.slice(0, params?.limit ?? 200) as AuditEvent[]);
    }
    return (await api.get('/audit', { params })).data;
  },
};

export const System = {
  health: async (): Promise<{ status: string }> =>
    isDemo() ? demoDelay(Demo.health()) : (await api.get('/system/health')).data,
  version: async (): Promise<{ version: string }> =>
    isDemo() ? demoDelay(Demo.version()) : (await api.get('/system/version')).data,
  license: async (): Promise<Record<string, unknown>> =>
    isDemo() ? demoDelay(Demo.license()) : (await api.get('/system/license')).data,
  dnsRegenerate: async (): Promise<{ reloaded: boolean; corefile_bytes: number }> =>
    isDemo() ? demoDelay(Demo.dnsRegenerate(), 320) : (await api.post('/system/dns/regenerate')).data,
};
