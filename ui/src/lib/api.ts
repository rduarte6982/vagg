import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';

/**
 * Wraps the FastAPI core (SPEC §5.1). The axios client lives at module scope so
 * a single interceptor adds the bearer token to every outbound request and a
 * second interceptor unwraps `vagg-core`'s domain errors into `ApiError`.
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
  inst.interceptors.response.use(
    (resp) => resp,
    (err: AxiosError) => unwrapError(err),
  );
  return inst;
}

export const api = makeClient();

// ----- Domain types (mirror vagg-core schemas) -----

export type VpnType = 'openvpn' | 'openconnect' | 'openfortivpn' | 'wireguard' | 'strongswan';
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
  created_at: string;
  updated_at: string;
}

export interface Consultant {
  id: number;
  email: string;
  name: string;
  openvpn_username?: string | null;
  static_pool_ip?: string | null;
  role: 'viewer' | 'operator' | 'admin';
  active: boolean;
  created_at: string;
  updated_at: string;
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
    const params = new URLSearchParams();
    params.set('username', email);
    params.set('password', password);
    const resp = await api.post('/auth/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return resp.data;
  },
  async refresh(refresh_token: string): Promise<{ access_token: string }> {
    const resp = await api.post('/auth/refresh', { refresh_token });
    return resp.data;
  },
  async me(): Promise<{ email: string; role: string }> {
    const resp = await api.get('/auth/me');
    return resp.data;
  },
};

export const Clients = {
  list: async (): Promise<Client[]> => (await api.get('/clients')).data,
  get: async (id: string): Promise<Client> => (await api.get(`/clients/${id}`)).data,
  create: async (body: Partial<Client>): Promise<Client> => (await api.post('/clients', body)).data,
  update: async (id: string, body: Partial<Client>): Promise<Client> =>
    (await api.patch(`/clients/${id}`, body)).data,
  remove: async (id: string): Promise<void> => {
    await api.delete(`/clients/${id}`);
  },
};

export const Tunnels = {
  status: async (clientId: string): Promise<TunnelStatusReport> =>
    (await api.get(`/tunnels/${clientId}/status`)).data,
  connect: async (clientId: string): Promise<TunnelStatusReport> =>
    (await api.post(`/tunnels/${clientId}/connect`)).data,
  disconnect: async (clientId: string): Promise<void> => {
    await api.post(`/tunnels/${clientId}/disconnect`);
  },
  sendOtp: async (clientId: string, code: string): Promise<void> => {
    await api.post(`/tunnels/${clientId}/otp`, { code });
  },
  logs: async (clientId: string, lines = 100): Promise<{ lines: string[] }> =>
    (await api.get(`/tunnels/${clientId}/logs`, { params: { lines } })).data,
};

export const Consultants = {
  list: async (): Promise<Consultant[]> => (await api.get('/consultants')).data,
  create: async (body: Partial<Consultant>): Promise<Consultant> =>
    (await api.post('/consultants', body)).data,
  update: async (id: number, body: Partial<Consultant>): Promise<Consultant> =>
    (await api.patch(`/consultants/${id}`, body)).data,
  remove: async (id: number): Promise<void> => {
    await api.delete(`/consultants/${id}`);
  },
};

export const Policies = {
  list: async (): Promise<Policy[]> => (await api.get('/policies')).data,
  create: async (body: Partial<Policy>): Promise<Policy> => (await api.post('/policies', body)).data,
  remove: async (id: number): Promise<void> => {
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
  }): Promise<AuditEvent[]> => (await api.get('/audit', { params })).data,
};

export const System = {
  health: async (): Promise<{ status: string }> => (await api.get('/system/health')).data,
  version: async (): Promise<{ version: string }> => (await api.get('/system/version')).data,
  license: async (): Promise<Record<string, unknown>> => (await api.get('/system/license')).data,
  dnsRegenerate: async (): Promise<{ reloaded: boolean; corefile_bytes: number }> =>
    (await api.post('/system/dns/regenerate')).data,
};
