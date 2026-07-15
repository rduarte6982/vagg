/**
 * Modo demonstração: permite testar a UI sem o vagg-core. Ativado quando:
 *   - import.meta.env.VITE_DEMO === 'true' (build de demo)
 *   - URL contém ?demo=1 (toggle pelo usuário)
 *   - ou localStorage 'vagg.demo' === '1' (lembrado entre sessões)
 *
 * Quando ligado, o cliente HTTP em `api.ts` desvia chamadas para os
 * handlers abaixo, que mantêm um banco de dados em memória persistido em
 * sessionStorage. Isso só serve para apresentação visual — autenticação
 * é fake (qualquer email/senha funciona).
 */

const STORAGE_KEY = 'vagg.demo.state';
const FLAG_KEY = 'vagg.demo';

export function isDemo(): boolean {
  if (typeof window === 'undefined') return false;
  if (import.meta.env.VITE_DEMO === 'true') return true;
  const params = new URLSearchParams(window.location.search);
  if (params.get('demo') === '1') {
    localStorage.setItem(FLAG_KEY, '1');
    return true;
  }
  if (params.get('demo') === '0') {
    localStorage.removeItem(FLAG_KEY);
    return false;
  }
  return localStorage.getItem(FLAG_KEY) === '1';
}

interface DemoNatMapping {
  virtual_cidr: string;
  real_cidr: string;
  description?: string | null;
}

interface DemoClient {
  id: string;
  name: string;
  vpn_type:
    | 'openvpn'
    | 'openconnect'
    | 'openfortivpn'
    | 'wireguard'
    | 'strongswan'
    | 'globalprotect';
  virtual_cidr: string;
  real_cidr: string;
  dns_server: string | null;
  description: string | null;
  nat_mappings: DemoNatMapping[];
  tunnel_state: 'stopped' | 'starting' | 'up' | 'down' | 'errored';
  created_at: string;
  updated_at: string;
}

interface DemoConsultant {
  id: number;
  email: string;
  name: string;
  has_password: boolean;
  openvpn_username: string | null;
  static_pool_ip: string | null;
  role: 'viewer' | 'operator' | 'admin';
  active: boolean;
  created_at: string;
  updated_at: string;
}

interface DemoPolicy {
  id: number;
  consultant_id: number;
  client_id: string;
  scope_kind: 'full' | 'subnet' | 'host';
  scope_value: string | null;
  expires_at: string | null;
  created_at: string;
}

interface DemoAuditEvent {
  id: string;
  event_type: string;
  actor_consultant_id: number | null;
  payload: Record<string, unknown> | null;
  prev_hash: string | null;
  hash: string;
  occurred_at: string;
}

interface DemoState {
  clients: DemoClient[];
  consultants: DemoConsultant[];
  policies: DemoPolicy[];
  audit: DemoAuditEvent[];
  nextConsultantId: number;
  nextPolicyId: number;
  nextAuditSeq: number;
}

function bootstrap(): DemoState {
  const now = new Date().toISOString();
  const earlier = new Date(Date.now() - 3600 * 1000).toISOString();
  const yesterday = new Date(Date.now() - 86400 * 1000).toISOString();

  const clients: DemoClient[] = [
    {
      id: 'petroleo',
      name: 'Petróleo SA',
      vpn_type: 'openvpn',
      virtual_cidr: '10.200.10.0/24',
      real_cidr: '172.16.0.0/24',
      dns_server: '172.16.0.10',
      description: 'Túnel principal de produção',
      nat_mappings: [],
      tunnel_state: 'up',
      created_at: yesterday,
      updated_at: now,
    },
    {
      id: 'lojas-ur',
      name: 'Lojas Urano',
      vpn_type: 'openconnect',
      virtual_cidr: '10.200.20.0/24',
      real_cidr: '10.10.0.0/16',
      dns_server: '10.10.0.5',
      description: null,
      nat_mappings: [],
      tunnel_state: 'up',
      created_at: yesterday,
      updated_at: now,
    },
    {
      id: 'banco-azul',
      name: 'Banco Azul',
      vpn_type: 'openfortivpn',
      virtual_cidr: '10.200.30.0/24',
      real_cidr: '192.168.50.0/24',
      dns_server: null,
      description: 'Acesso temporário · projeto Athena',
      nat_mappings: [],
      tunnel_state: 'starting',
      created_at: earlier,
      updated_at: now,
    },
    {
      id: 'cooperativa',
      name: 'Cooperativa do Sul',
      vpn_type: 'wireguard',
      virtual_cidr: '10.200.40.0/24',
      real_cidr: '10.20.0.0/24',
      dns_server: null,
      description: null,
      nat_mappings: [],
      tunnel_state: 'errored',
      created_at: yesterday,
      updated_at: now,
    },
    {
      id: 'industria-x',
      name: 'Indústria X',
      vpn_type: 'strongswan',
      virtual_cidr: '10.200.50.0/24',
      real_cidr: '10.50.0.0/24',
      dns_server: '10.50.0.1',
      description: null,
      nat_mappings: [],
      tunnel_state: 'stopped',
      created_at: yesterday,
      updated_at: yesterday,
    },
  ];

  const consultants: DemoConsultant[] = [
    {
      id: 1,
      email: 'admin@vagg.local',
      name: 'Administrador',
      has_password: true,
      openvpn_username: 'admin',
      static_pool_ip: '10.8.0.2',
      role: 'admin',
      active: true,
      created_at: yesterday,
      updated_at: yesterday,
    },
    {
      id: 2,
      email: 'paulo.silva@consultoria.com',
      name: 'Paulo Silva',
      has_password: true,
      openvpn_username: 'paulo',
      static_pool_ip: '10.8.0.5',
      role: 'operator',
      active: true,
      created_at: yesterday,
      updated_at: yesterday,
    },
    {
      id: 3,
      email: 'beatriz.lima@consultoria.com',
      name: 'Beatriz Lima',
      has_password: false,
      openvpn_username: 'beatriz',
      static_pool_ip: '10.8.0.6',
      role: 'viewer',
      active: true,
      created_at: yesterday,
      updated_at: yesterday,
    },
    {
      id: 4,
      email: 'andre.romero@consultoria.com',
      name: 'André Romero',
      has_password: true,
      openvpn_username: 'andre',
      static_pool_ip: null,
      role: 'operator',
      active: false,
      created_at: yesterday,
      updated_at: yesterday,
    },
  ];

  const policies: DemoPolicy[] = [
    {
      id: 1,
      consultant_id: 2,
      client_id: 'petroleo',
      scope_kind: 'full',
      scope_value: null,
      expires_at: null,
      created_at: yesterday,
    },
    {
      id: 2,
      consultant_id: 2,
      client_id: 'lojas-ur',
      scope_kind: 'subnet',
      scope_value: '10.10.5.0/24',
      expires_at: null,
      created_at: yesterday,
    },
    {
      id: 3,
      consultant_id: 3,
      client_id: 'banco-azul',
      scope_kind: 'host',
      scope_value: '192.168.50.10',
      expires_at: new Date(Date.now() + 86400 * 7 * 1000).toISOString(),
      created_at: earlier,
    },
  ];

  const audit: DemoAuditEvent[] = [
    {
      id: 'evt-001',
      event_type: 'auth.login.success',
      actor_consultant_id: 1,
      payload: { ip: '10.0.0.5' },
      prev_hash: null,
      hash: 'abc123',
      occurred_at: now,
    },
    {
      id: 'evt-002',
      event_type: 'tunnel.connect',
      actor_consultant_id: 1,
      payload: { client_id: 'petroleo' },
      prev_hash: 'abc123',
      hash: 'def456',
      occurred_at: now,
    },
    {
      id: 'evt-003',
      event_type: 'policy.create',
      actor_consultant_id: 1,
      payload: { consultant_id: 3, client_id: 'banco-azul' },
      prev_hash: 'def456',
      hash: 'ghi789',
      occurred_at: earlier,
    },
    {
      id: 'evt-004',
      event_type: 'tunnel.error',
      actor_consultant_id: null,
      payload: { client_id: 'cooperativa', error: 'handshake timeout' },
      prev_hash: 'ghi789',
      hash: 'jkl012',
      occurred_at: earlier,
    },
  ];

  return {
    clients,
    consultants,
    policies,
    audit,
    nextConsultantId: 5,
    nextPolicyId: 4,
    nextAuditSeq: 5,
  };
}

function load(): DemoState {
  if (typeof window === 'undefined') return bootstrap();
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as DemoState;
  } catch {
    // ignore
  }
  const initial = bootstrap();
  save(initial);
  return initial;
}

function save(state: DemoState) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore quota errors
  }
}

let _state: DemoState | null = null;
function db(): DemoState {
  if (!_state) _state = load();
  return _state;
}

function commit() {
  if (_state) save(_state);
}

function nowIso() {
  return new Date().toISOString();
}

function pushAudit(event_type: string, payload: Record<string, unknown>) {
  const s = db();
  const seq = s.nextAuditSeq++;
  s.audit.unshift({
    id: `evt-${String(seq).padStart(3, '0')}`,
    event_type,
    actor_consultant_id: 1,
    payload,
    prev_hash: s.audit[0]?.hash ?? null,
    hash: Math.random().toString(36).slice(2, 10),
    occurred_at: nowIso(),
  });
}

export interface DemoLoginResult {
  access_token: string;
  refresh_token: string;
}

export const Demo = {
  resetState() {
    _state = bootstrap();
    save(_state);
  },

  login(email: string, _password: string): DemoLoginResult {
    pushAudit('auth.login.success', { email });
    return { access_token: 'demo.access.token', refresh_token: 'demo.refresh.token' };
  },

  me() {
    return { email: 'admin@vagg.local', role: 'admin' };
  },

  // ---- Clients ----
  listClients(): DemoClient[] {
    return [...db().clients];
  },
  createClient(body: Partial<DemoClient>): DemoClient {
    const s = db();
    if (!body.id || !body.name || !body.vpn_type) {
      throw new Error('id, name e vpn_type são obrigatórios');
    }
    if (s.clients.some((c) => c.id === body.id)) {
      throw new Error(`Cliente "${body.id}" já existe`);
    }
    const created: DemoClient = {
      id: body.id,
      name: body.name,
      vpn_type: body.vpn_type,
      virtual_cidr: body.virtual_cidr ?? '10.200.99.0/24',
      real_cidr: body.real_cidr ?? '10.0.0.0/24',
      dns_server: body.dns_server ?? null,
      description: body.description ?? null,
      nat_mappings: (body.nat_mappings ?? []) as DemoNatMapping[],
      tunnel_state: 'stopped',
      created_at: nowIso(),
      updated_at: nowIso(),
    };
    s.clients.push(created);
    pushAudit('client.create', { client_id: created.id });
    commit();
    return created;
  },
  removeClient(id: string) {
    const s = db();
    s.clients = s.clients.filter((c) => c.id !== id);
    pushAudit('client.delete', { client_id: id });
    commit();
  },
  connectTunnel(id: string) {
    const s = db();
    const c = s.clients.find((x) => x.id === id);
    if (!c) throw new Error('cliente não encontrado');
    c.tunnel_state = 'starting';
    c.updated_at = nowIso();
    pushAudit('tunnel.connect', { client_id: id });
    setTimeout(() => {
      const cc = db().clients.find((x) => x.id === id);
      if (cc && cc.tunnel_state === 'starting') {
        cc.tunnel_state = 'up';
        cc.updated_at = nowIso();
        commit();
      }
    }, 1500);
    commit();
    return { state: c.tunnel_state, container_id: 'demo-container', uptime_s: 0 };
  },
  disconnectTunnel(id: string) {
    const s = db();
    const c = s.clients.find((x) => x.id === id);
    if (!c) throw new Error('cliente não encontrado');
    c.tunnel_state = 'stopped';
    c.updated_at = nowIso();
    pushAudit('tunnel.disconnect', { client_id: id });
    commit();
  },

  // ---- Consultants ----
  listConsultants(): DemoConsultant[] {
    return [...db().consultants];
  },
  createConsultant(body: Partial<DemoConsultant> & { password?: string }): DemoConsultant {
    const s = db();
    if (!body.email) throw new Error('email é obrigatório');
    const created: DemoConsultant = {
      id: s.nextConsultantId++,
      email: body.email,
      name: body.name ?? body.email.split('@')[0],
      has_password: !!body.password,
      openvpn_username: body.openvpn_username ?? null,
      static_pool_ip: body.static_pool_ip ?? null,
      role: body.role ?? 'viewer',
      active: body.active ?? true,
      created_at: nowIso(),
      updated_at: nowIso(),
    };
    s.consultants.push(created);
    pushAudit('consultant.create', { consultant_id: created.id });
    commit();
    return created;
  },
  updateConsultant(id: number, body: Partial<DemoConsultant>): DemoConsultant | undefined {
    const s = db();
    const c = s.consultants.find((x) => x.id === id);
    if (!c) return undefined;
    Object.assign(c, body, { updated_at: nowIso() });
    pushAudit('consultant.update', { consultant_id: id });
    commit();
    return c;
  },
  setConsultantPassword(id: number): DemoConsultant | undefined {
    const s = db();
    const c = s.consultants.find((x) => x.id === id);
    if (!c) return undefined;
    c.has_password = true;
    c.updated_at = nowIso();
    pushAudit('consultant.password_set', { consultant_id: id });
    commit();
    return c;
  },
  removeConsultant(id: number) {
    const s = db();
    s.consultants = s.consultants.filter((c) => c.id !== id);
    s.policies = s.policies.filter((p) => p.consultant_id !== id);
    pushAudit('consultant.delete', { consultant_id: id });
    commit();
  },

  // ---- Policies ----
  listPolicies(): DemoPolicy[] {
    return [...db().policies];
  },
  createPolicy(body: Partial<DemoPolicy>): DemoPolicy {
    const s = db();
    if (!body.consultant_id || !body.client_id) {
      throw new Error('consultant_id e client_id são obrigatórios');
    }
    const created: DemoPolicy = {
      id: s.nextPolicyId++,
      consultant_id: body.consultant_id,
      client_id: body.client_id,
      scope_kind: body.scope_kind ?? 'full',
      scope_value: body.scope_value ?? null,
      expires_at: body.expires_at ?? null,
      created_at: nowIso(),
    };
    s.policies.push(created);
    pushAudit('policy.create', {
      consultant_id: created.consultant_id,
      client_id: created.client_id,
    });
    commit();
    return created;
  },
  removePolicy(id: number) {
    const s = db();
    s.policies = s.policies.filter((p) => p.id !== id);
    pushAudit('policy.delete', { policy_id: id });
    commit();
  },

  // ---- Audit / System ----
  listAudit(): DemoAuditEvent[] {
    return [...db().audit];
  },
  health() {
    return { status: 'ok' };
  },
  version() {
    return { version: '0.1.0-demo' };
  },
  license() {
    return { status: 'active', tier: 'demo', clients_allowed: 25, expires: '2099-12-31' };
  },
  dnsRegenerate() {
    pushAudit('system.dns.regenerate', {});
    return { reloaded: true, corefile_bytes: 1842 };
  },
};
