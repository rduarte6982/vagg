import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  FileText,
  Loader2,
  Pencil,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from 'lucide-react';
import { Tooltip } from '@/components/ui/tooltip';
import { useToasts } from '@/components/ui/toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal';
import { PageHeader } from '@/components/ui/page-header';
import { Select } from '@/components/ui/select';
import { StatusLed, type LedState } from '@/components/ui/status-led';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Clients, Saml, Tunnels, type Client, type TunnelState, type VpnType } from '@/lib/api';
import { usePoll } from '@/lib/polling';

const VPN_TYPES: VpnType[] = [
  'openvpn',
  'openconnect',
  'openfortivpn',
  'globalprotect',
  'wireguard',
  'strongswan',
];

const VPN_TYPE_LABEL: Record<VpnType, string> = {
  openvpn: 'OpenVPN',
  openconnect: 'OpenConnect (Cisco AnyConnect)',
  openfortivpn: 'OpenFortiVPN (FortiGate SSL-VPN)',
  globalprotect: 'GlobalProtect (Palo Alto)',
  wireguard: 'WireGuard',
  strongswan: 'StrongSwan (IPsec)',
};

const STATE_TO_LED: Record<TunnelState, LedState> = {
  up: 'on',
  starting: 'warn',
  down: 'warn',
  errored: 'error',
  stopped: 'off',
};

interface ParsedOvpn {
  remote_host?: string;
  remote_port?: string;
  pushed_routes: string[]; // CIDRs detectados em push "route ..."
  dns?: string;
  needs_auth: boolean;
}

/**
 * Extrai metadados do conteúdo de um arquivo .ovpn ou .conf:
 *   - remote (host/porta) → util pra mostrar destino
 *   - push "route X.X.X.X 255.255.255.0" → real_cidr candidato
 *   - dhcp-option DNS X.X.X.X → DNS interno
 *   - auth-user-pass → exige user/senha
 */
function parseOvpnContent(text: string): ParsedOvpn {
  const out: ParsedOvpn = { pushed_routes: [], needs_auth: false };

  for (const line of text.split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;

    // remote <host> [port]
    const remoteMatch = t.match(/^remote\s+(\S+)(?:\s+(\d+))?/);
    if (remoteMatch && !out.remote_host) {
      out.remote_host = remoteMatch[1];
      if (remoteMatch[2]) out.remote_port = remoteMatch[2];
    }

    // push "route 10.20.0.0 255.255.0.0"
    const pushRoute = t.match(/push\s+"\s*route\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s*"/);
    if (pushRoute) {
      const cidr = maskToCidr(pushRoute[1], pushRoute[2]);
      if (cidr) out.pushed_routes.push(cidr);
    }

    // route 10.20.0.0 255.255.0.0 (sem push, mas válido)
    const route = t.match(/^route\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)/);
    if (route) {
      const cidr = maskToCidr(route[1], route[2]);
      if (cidr) out.pushed_routes.push(cidr);
    }

    // dhcp-option DNS X.X.X.X (em push "...")
    const dnsMatch = t.match(/dhcp-option\s+DNS\s+(\d+\.\d+\.\d+\.\d+)/);
    if (dnsMatch && !out.dns) out.dns = dnsMatch[1];

    if (/^auth-user-pass\b/.test(t)) out.needs_auth = true;
  }

  return out;
}

function maskToCidr(network: string, mask: string): string | null {
  const parts = mask.split('.').map(Number);
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return null;
  let bits = 0;
  let seenZero = false;
  for (const oct of parts) {
    for (let i = 7; i >= 0; i--) {
      if (((oct >> i) & 1) === 1) {
        if (seenZero) return null;
        bits++;
      } else {
        seenZero = true;
      }
    }
  }
  return `${network}/${bits}`;
}

/** Próximo /24 livre dentro de 10.200.0.0/16, evitando colisão com clientes existentes. */
function nextVirtualCidr(usedClients: Client[]): string {
  const used = new Set<number>();
  for (const c of usedClients) {
    const m = c.virtual_cidr.match(/^10\.200\.(\d+)\./);
    if (m) used.add(Number(m[1]));
  }
  for (let i = 10; i <= 254; i++) {
    if (!used.has(i)) return `10.200.${i}.0/24`;
  }
  return '10.200.99.0/24';
}

interface NewClientForm {
  id: string;
  name: string;
  vpn_type: VpnType;
  virtual_cidr: string;
  real_cidr: string;
  dns_server: string;
  config_text: string;
  vpn_username: string;
  vpn_password: string;
  // campos dedicados pra openfortivpn — UI monta o config_text a partir deles
  forti_host: string;
  forti_port: string;
  forti_trusted_cert: string;
  // Tipo de autenticação MFA: none / otp / saml
  auth_method: 'none' | 'otp' | 'saml';
}

const EMPTY_FORM: NewClientForm = {
  id: '',
  name: '',
  vpn_type: 'openvpn',
  virtual_cidr: '',
  real_cidr: '',
  dns_server: '',
  config_text: '',
  vpn_username: '',
  vpn_password: '',
  forti_host: '',
  forti_port: '10443',
  forti_trusted_cert: '',
  auth_method: 'none',
};

/** Monta o config-file do openfortivpn a partir dos campos dedicados. */
function buildFortiConfig(host: string, port: string, trustedCert: string): string {
  const lines = [
    `host = ${host.trim()}`,
    `port = ${port.trim() || '10443'}`,
  ];
  if (trustedCert.trim()) {
    lines.push(`trusted-cert = ${trustedCert.trim()}`);
  } else {
    lines.push(`insecure-ssl = 1`);
  }
  return lines.join('\n') + '\n';
}

export function ClientsPage() {
  const { t } = useTranslation();
  const toast = useToasts();
  const list = usePoll(Clients.list, 5_000);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<NewClientForm>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Client | null>(null);
  // Form de edição inclui campos write-only (config_text, user, password) que
  // o GET /clients não retorna. Vazio = não toca no valor atual.
  const [editForm, setEditForm] = useState<{
    name: string;
    description: string;
    virtual_cidr: string;
    real_cidr: string;
    dns_server: string;
    config_text: string;
    vpn_username: string;
    vpn_password: string;
    forti_host: string;
    forti_port: string;
    forti_trusted_cert: string;
    extra_routes: string[];
    auth_method: 'none' | 'otp' | 'saml';
  } | null>(null);
  const [editLoading, setEditLoading] = useState(false);
  const editFileRef = useRef<HTMLInputElement>(null);
  const [editUploadInfo, setEditUploadInfo] = useState<string | null>(null);
  const [logsFor, setLogsFor] = useState<string | null>(null);
  const [logsContent, setLogsContent] = useState<string>('');
  const [logsLoading, setLogsLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadInfo, setUploadInfo] = useState<string | null>(null);

  const set = <K extends keyof NewClientForm>(k: K, v: NewClientForm[K]) =>
    setForm((p) => ({ ...p, [k]: v }));

  const submitNew = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    // Validação client-side dos campos exigidos pelo método de auth.
    if (form.auth_method === 'saml' || form.auth_method === 'otp') {
      if (!form.vpn_username.trim()) {
        setError(
          form.auth_method === 'saml'
            ? 'Usuário VPN é obrigatório no SAML — informe o email/UPN do AD que bate com o login Microsoft.'
            : 'Usuário VPN é obrigatório quando o método é OTP.',
        );
        return;
      }
    }
    if (form.auth_method === 'otp' && !form.vpn_password.trim()) {
      setError('Senha VPN é obrigatória quando o método é OTP.');
      return;
    }
    try {
      const realCidr = form.real_cidr.trim() || '0.0.0.0/0';

      // Pra openfortivpn, montamos o config-file a partir dos campos dedicados
      // se ainda não veio nada no textarea (ou se o user só preencheu host/port).
      let configText = form.config_text.trim();
      if (form.vpn_type === 'openfortivpn' && form.forti_host.trim()) {
        const built = buildFortiConfig(form.forti_host, form.forti_port, form.forti_trusted_cert);
        // se o textarea estiver vazio OU não tiver "host = " (provavelmente edição),
        // sobrescreve com o gerado pelos campos dedicados.
        if (!configText || !/^host\s*=/m.test(configText)) {
          configText = built;
        }
      }

      await Clients.create({
        ...form,
        real_cidr: realCidr,
        dns_server: form.dns_server || null,
        config_text: configText || null,
        nat_mappings: [],
      } as Partial<Client>);
      setShowCreate(false);
      setForm(EMPTY_FORM);
      await list.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const remove = async (id: string) => {
    if (!confirm(t('clients.delete_confirm'))) return;
    await Clients.remove(id);
    await list.refetch();
  };

  // Estado pro fluxo de OTP/MFA: quando o cliente tem requires_otp,
  // o botão "Conectar" abre um modal pedindo o código antes de iniciar.
  const [otpModalFor, setOtpModalFor] = useState<Client | null>(null);
  const [otpCode, setOtpCode] = useState('');
  const [otpBusy, setOtpBusy] = useState(false);

  const connect = async (id: string) => {
    const c = (list.data ?? []).find((x) => x.id === id);
    if (!c) return;
    const method = c.auth_method ?? (c.requires_otp ? 'otp' : 'none');
    if (method === 'otp') {
      setOtpModalFor(c);
      setOtpCode('');
      return;
    }
    if (method === 'saml') {
      // Se já tem cookie válido, conecta direto
      const exp = c.saml_cookie_expires_at
        ? new Date(c.saml_cookie_expires_at).getTime()
        : 0;
      if (c.has_saml_cookie && exp > Date.now()) {
        await connectInternal(id);
        return;
      }
      // Cookie ausente/expirado → abre o portal SAML (browser remoto em iframe)
      await startSamlPortal(c);
      return;
    }
    await connectInternal(id);
  };

  // ── Modal SAML connect — abre browser remoto (saml-portal) num iframe.
  // O usuário completa o login Microsoft DENTRO do iframe; o container captura
  // o cookie via mitmproxy e nós damos connect automático. Não usa cookie do
  // browser local porque o gateway GP geralmente faz IP-binding e o cookie
  // capturado de outro IP é rejeitado.
  const [samlConnectFor, setSamlConnectFor] = useState<Client | null>(null);
  const [samlPortalUrl, setSamlPortalUrl] = useState<string | null>(null);
  const [samlConnectBusy, setSamlConnectBusy] = useState(false);
  const [samlConnectStatus, setSamlConnectStatus] = useState<
    'idle' | 'starting' | 'waiting' | 'captured' | 'error'
  >('idle');
  const [samlConnectError, setSamlConnectError] = useState<string | null>(null);

  const startSamlPortal = async (c: Client) => {
    setSamlConnectFor(c);
    setSamlPortalUrl(null);
    setSamlConnectStatus('starting');
    setSamlConnectError(null);
    setSamlConnectBusy(true);
    try {
      const sess = await Saml.start(c.id);
      setSamlPortalUrl(sess.portal_url);
      setSamlConnectStatus('waiting');
      toast.info('Portal SAML aberto', 'Complete o login Microsoft no painel abaixo.');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSamlConnectError(msg);
      setSamlConnectStatus('error');
      toast.error('Falha ao abrir portal SAML', msg);
    } finally {
      setSamlConnectBusy(false);
    }
  };

  const closeSamlConnect = async () => {
    const c = samlConnectFor;
    setSamlConnectFor(null);
    setSamlPortalUrl(null);
    setSamlConnectStatus('idle');
    setSamlConnectError(null);
    if (c) {
      // Não bloqueia a UI; só pede pro orchestrator derrubar o container.
      Saml.stopPortal(c.id).catch(() => {});
    }
  };

  // Polling do cookie enquanto o modal SAML estiver aberto e em waiting.
  useEffect(() => {
    if (!samlConnectFor || samlConnectStatus !== 'waiting') return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled || !samlConnectFor) return;
      try {
        const r = await Saml.poll(samlConnectFor.id);
        if (cancelled) return;
        if (r.captured) {
          setSamlConnectStatus('captured');
          toast.success('Cookie capturado', 'Iniciando o túnel…');
          try {
            await Tunnels.connect(samlConnectFor.id);
            toast.success(
              'Conexão disparada',
              `Túnel "${samlConnectFor.id}" iniciando.`,
            );
            await list.refetch();
          } catch (err) {
            toast.error(
              'Falha ao conectar',
              err instanceof Error ? err.message : String(err),
            );
          }
          await closeSamlConnect();
          return;
        }
        if (r.error) {
          setSamlConnectStatus('error');
          setSamlConnectError(r.error);
          return;
        }
      } catch {
        // ignora erros transientes do polling
      }
    };
    const iv = setInterval(tick, 2500);
    // Primeiro tick imediato (mas só após o portal subir)
    tick();
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [samlConnectFor?.id, samlConnectStatus]);

  const connectInternal = async (id: string) => {
    setBusyId(id);
    toast.info('Conectando…', `Iniciando túnel para "${id}"`);
    try {
      await Tunnels.connect(id);
      toast.success('Conexão disparada', `O túnel "${id}" está sendo estabelecido — acompanhe o LED.`);
    } catch (err) {
      toast.error('Falha ao conectar', err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
      await list.refetch();
    }
  };

  const submitOtp = async () => {
    if (!otpModalFor) return;
    if (!/^\d{4,8}$/.test(otpCode.trim())) {
      toast.error('Código inválido', 'Cole o código de 6 dígitos do app autenticador.');
      return;
    }
    setOtpBusy(true);
    const id = otpModalFor.id;
    try {
      // 1. dispara o connect (container abre, espera no FIFO)
      await Tunnels.connect(id);
      // 2. aguarda o container começar (controller socket pronto + openfortivpn
      //    chegando no prompt do token)
      await new Promise((r) => setTimeout(r, 2500));
      // 3. envia o OTP — orchestrator → tunnel-controller → FIFO → stdin
      await Tunnels.sendOtp(id, otpCode.trim());
      toast.success(
        'Código enviado',
        `Token entregue ao "${id}". Acompanhe o LED — fica verde quando autenticar.`,
      );
      setOtpModalFor(null);
      setOtpCode('');
    } catch (err) {
      toast.error('Falha no OTP', err instanceof Error ? err.message : String(err));
    } finally {
      setOtpBusy(false);
      await list.refetch();
    }
  };

  // SAML/SSO: estado do modal de browser remoto
  // (modal SAML connect — definido mais abaixo, perto do JSX)

  const disconnect = async (id: string) => {
    setBusyId(id);
    toast.info('Desconectando…', `Encerrando túnel "${id}"`);
    try {
      await Tunnels.disconnect(id);
      toast.success('Desconectado', `Túnel "${id}" encerrado.`);
    } catch (err) {
      toast.error('Falha ao desconectar', err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
      await list.refetch();
    }
  };

  const openLogs = async (id: string) => {
    setLogsFor(id);
    setLogsContent('');
    setLogsLoading(true);
    try {
      const r = await Tunnels.logs(id, 200);
      const lines = r.lines.join('\n');
      // Inclui o último erro registrado pelo orchestrator no topo, se houver.
      // Útil quando logs vem vazio mas o tunnel_state == errored.
      const c = list.data?.find((x) => x.id === id);
      if (c?.tunnel_state === 'errored' && c.tunnel_last_error) {
        setLogsContent(
          `[orchestrator] estado: errored\n[orchestrator] último erro: ${c.tunnel_last_error}\n[orchestrator] checagem: ${c.tunnel_last_check_at ?? '—'}\n\n──── logs do container ────\n${lines || '(container não encontrado ou sem logs)'}`,
        );
      } else {
        setLogsContent(lines || '(sem logs)');
      }
    } catch (err) {
      const c = list.data?.find((x) => x.id === id);
      const orchestratorErr =
        c?.tunnel_state === 'errored' && c.tunnel_last_error
          ? `\n\n[orchestrator] último erro: ${c.tunnel_last_error}`
          : '';
      const msg = err instanceof Error ? err.message : String(err);
      // Heurística: se for "Not Found" e o tunnel state é errored, é provável
      // que o container nunca tenha sido criado ou que o orchestrator não
      // consegue falar com o Docker daemon.
      let diagnosis = '';
      if (msg.includes('Not Found') || msg.includes('404')) {
        diagnosis =
          '\n\nDiagnóstico: container do túnel não está rodando ou o ' +
          'orchestrator não consegue acessar a Docker API. Em servidores ' +
          'Linux, isso geralmente é permissão do socket ' +
          '(/var/run/docker.sock precisa estar legível pro group do user ' +
          'vagg). Cheque os logs do vagg-core: ' +
          '`docker logs vagg-vagg-core-1 | grep docker.sock`.';
      }
      setLogsContent(`Erro ao buscar logs: ${msg}${orchestratorErr}${diagnosis}`);
    } finally {
      setLogsLoading(false);
    }
  };

  /**
   * Handler de upload do arquivo de config (.ovpn/.conf/.wg). Lê o conteúdo
   * via FileReader, popula `config_text`, e tenta auto-preencher:
   *   - vpn_type baseado no formato (presença de "client + dev tun" → openvpn,
   *     "[Interface]" + "[Peer]" → wireguard, "host =" + "port =" → openfortivpn)
   *   - id (slug) baseado no nome do arquivo
   *   - name baseado no nome do arquivo
   */
  const handleFileUpload = async (file: File) => {
    setUploadInfo(null);
    try {
      const txt = await file.text();
      const lower = txt.toLowerCase();

      let detected: VpnType = form.vpn_type;
      if (lower.includes('[interface]') && lower.includes('[peer]')) {
        detected = 'wireguard';
      } else if (/^\s*host\s*=/.test(txt) && /^\s*port\s*=/m.test(txt)) {
        detected = 'openfortivpn';
      } else if (/^\s*conn\b/m.test(txt) || /strongswan|swanctl/i.test(txt)) {
        detected = 'strongswan';
      } else if (lower.includes('<ca>') || /^\s*remote\s+/m.test(txt)) {
        detected = 'openvpn';
      }

      const baseName = file.name.replace(/\.(ovpn|conf|wg)$/i, '');
      const slug = baseName
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
        .slice(0, 32);

      const parsed = parseOvpnContent(txt);

      // virtual_cidr: pega próximo /24 livre dentro do range reservado
      const autoVirtual = nextVirtualCidr(list.data ?? []);

      // real_cidr: primeira push route que não seja 0.0.0.0 (gateway redirect)
      const validRoutes = parsed.pushed_routes.filter(
        (r) => !r.startsWith('0.0.0.0/') && !r.startsWith('128.0.0.0/'),
      );
      const autoReal = validRoutes[0] ?? '';

      setForm((p) => ({
        ...p,
        config_text: txt,
        vpn_type: detected,
        id: p.id || slug,
        name: p.name || baseName,
        dns_server: p.dns_server || (parsed.dns ?? ''),
        virtual_cidr: p.virtual_cidr || autoVirtual,
        real_cidr: p.real_cidr || autoReal,
      }));

      const lines = txt.split(/\r?\n/).length;
      const parts: string[] = [`${file.name} carregado (${lines} linhas)`];
      parts.push(`protocolo: ${detected}`);
      if (parsed.remote_host) {
        parts.push(`remote: ${parsed.remote_host}${parsed.remote_port ? ':' + parsed.remote_port : ''}`);
      }
      if (validRoutes.length > 0) {
        parts.push(`${validRoutes.length} push route(s) detectada(s)`);
      } else {
        parts.push('sem push routes — preencha CIDR real manualmente');
      }
      if (parsed.dns) parts.push(`DNS interno: ${parsed.dns}`);
      if (parsed.needs_auth) parts.push('precisa user/senha');
      setUploadInfo(parts.join(' · '));
    } catch (err) {
      setUploadInfo(`Erro lendo arquivo: ${err instanceof Error ? err.message : err}`);
    }
  };

  const fillAutoVirtual = () => {
    setForm((p) => ({ ...p, virtual_cidr: nextVirtualCidr(list.data ?? []) }));
  };

  const openEdit = async (c: Client) => {
    setEditing(c);
    setEditLoading(true);
    const initialExtras = (c.nat_mappings ?? []).map((m) => m.real_cidr);
    setEditForm({
      name: c.name,
      description: c.description ?? '',
      virtual_cidr: c.virtual_cidr,
      real_cidr: c.real_cidr,
      dns_server: c.dns_server ?? '',
      config_text: '',
      vpn_username: '',
      vpn_password: '',
      forti_host: '',
      forti_port: '10443',
      forti_trusted_cert: '',
      extra_routes: initialExtras,
      auth_method: c.auth_method ?? (c.requires_otp ? 'otp' : 'none'),
    });
    setEditUploadInfo(null);

    try {
      const snap = await Clients.getConfig(c.id);
      const cfg = snap.config_text ?? '';
      let fHost = '';
      let fPort = '10443';
      let fCert = '';
      if (c.vpn_type === 'openfortivpn' && cfg) {
        const hostM = cfg.match(/^\s*host\s*=\s*(\S+)/m);
        const portM = cfg.match(/^\s*port\s*=\s*(\d+)/m);
        const certM = cfg.match(/^\s*trusted-cert\s*=\s*([0-9a-fA-F]+)/m);
        if (hostM) fHost = hostM[1];
        if (portM) fPort = portM[1];
        if (certM) fCert = certM[1];
      }
      setEditForm((p) =>
        p
          ? {
              ...p,
              config_text: cfg,
              vpn_username: snap.vpn_username ?? '',
              forti_host: fHost,
              forti_port: fPort,
              forti_trusted_cert: fCert,
            }
          : p,
      );
    } catch (err) {
      toast.error('Falha ao carregar dados', err instanceof Error ? err.message : String(err));
    } finally {
      setEditLoading(false);
    }
  };

  const handleEditFileUpload = async (file: File) => {
    setEditUploadInfo(null);
    try {
      const txt = await file.text();
      setEditForm((p) => (p ? { ...p, config_text: txt } : p));
      const lines = txt.split(/\r?\n/).length;
      setEditUploadInfo(`${file.name} carregado (${lines} linhas)`);
    } catch (err) {
      setEditUploadInfo(`Erro: ${err instanceof Error ? err.message : err}`);
    }
  };

  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing || !editForm) return;
    setError(null);
    // Pra OTP/SAML: precisa de vpn_username preenchido (ou no form, ou já
    // persistido no cliente). Como o GET /clients/:id/config já trouxe
    // vpn_username pro form quando existia, basta checar o que tá no form.
    if (editForm.auth_method === 'saml' || editForm.auth_method === 'otp') {
      if (!editForm.vpn_username.trim()) {
        const msg =
          editForm.auth_method === 'saml'
            ? 'Usuário VPN é obrigatório no SAML — informe o email/UPN do AD que bate com o login Microsoft.'
            : 'Usuário VPN é obrigatório quando o método é OTP.';
        setError(msg);
        toast.error('Falta preencher', msg);
        return;
      }
    }
    if (editForm.auth_method === 'otp') {
      // OTP exige senha. Como o form trata vazio = "manter atual", só
      // bloqueia se o cliente também não tem senha persistida (has_credentials
      // é true quando user OU senha estão setados; checamos via has_credentials
      // + presença no form).
      const hasFormPwd = editForm.vpn_password.trim().length > 0;
      const hasStoredCreds = editing.has_credentials;
      if (!hasFormPwd && !hasStoredCreds) {
        const msg = 'Senha VPN é obrigatória quando o método é OTP.';
        setError(msg);
        toast.error('Falta preencher', msg);
        return;
      }
    }
    try {
      const payload: Partial<Client> & {
        vpn_username?: string | null;
        vpn_password?: string | null;
        description?: string | null;
      } = {
        name: editForm.name,
        description: editForm.description || null,
        virtual_cidr: editForm.virtual_cidr,
        real_cidr: editForm.real_cidr.trim() || '0.0.0.0/0',
        dns_server: editForm.dns_server || null,
      };

      // Pra openfortivpn: se admin alterou Gateway/Porta/Cert, regera o
      // config_text a partir desses campos (mantendo regras: prevalece o que
      // o admin colocar no textarea).
      let configToSend = editForm.config_text;
      if (editing.vpn_type === 'openfortivpn' && editForm.forti_host.trim()) {
        configToSend = buildFortiConfig(
          editForm.forti_host,
          editForm.forti_port,
          editForm.forti_trusted_cert,
        );
      }
      if (configToSend.trim()) {
        (payload as { config_text?: string }).config_text = configToSend;
      }
      if (editForm.vpn_username.trim()) {
        payload.vpn_username = editForm.vpn_username;
      }
      if (editForm.vpn_password.trim()) {
        payload.vpn_password = editForm.vpn_password;
      }
      // Tipo de autenticação (none/otp/saml) — backend sincroniza requires_otp
      (payload as { auth_method?: string }).auth_method = editForm.auth_method;
      // Redes adicionais (nat_mappings) — admin gerencia via UI
      const cleanExtras = editForm.extra_routes
        .map((r) => r.trim())
        .filter((r) => r && /^\d+\.\d+\.\d+\.\d+\/\d+$/.test(r));
      (payload as { nat_mappings?: { virtual_cidr: string; real_cidr: string }[] }).nat_mappings =
        cleanExtras.map((cidr) => ({ virtual_cidr: cidr, real_cidr: cidr }));
      await Clients.update(editing.id, payload);
      toast.success('Cliente atualizado', `"${editing.name}" salvo.`);
      setEditing(null);
      setEditForm(null);
      await list.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast.error('Falha ao salvar', err instanceof Error ? err.message : String(err));
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return list.data ?? [];
    return (list.data ?? []).filter(
      (c) =>
        c.id.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        c.real_cidr.toLowerCase().includes(q),
    );
  }, [list.data, search]);

  return (
    <div>
      <PageHeader
        title={t('clients.title')}
        description={t('clients.subtitle')}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => list.refetch()}>
              <RefreshCw size={14} className="mr-1.5" />
              {t('common.refresh')}
            </Button>
            <Button
              size="sm"
              onClick={() => {
                // pré-preenche virtual_cidr com o próximo /24 livre
                setForm((p) => ({ ...p, virtual_cidr: p.virtual_cidr || nextVirtualCidr(list.data ?? []) }));
                setShowCreate(true);
              }}
            >
              <Plus size={14} className="mr-1.5" />
              {t('clients.create')}
            </Button>
          </>
        }
      />

      <Card>
        <CardContent className="px-0 py-0">
          <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
            <div className="relative max-w-sm flex-1">
              <Search
                size={14}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                placeholder="Buscar por id, nome ou CIDR..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8"
              />
            </div>
            <span className="text-xs text-muted-foreground">
              {filtered.length} cliente(s)
            </span>
          </div>

          {list.error && (
            <p className="px-5 py-3 text-sm text-destructive">{list.error}</p>
          )}

          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 px-5 py-16 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-primary">
                <Plus size={20} />
              </div>
              <p className="text-sm text-muted-foreground">
                {search ? 'Nenhum cliente bate com o filtro.' : t('clients.no_clients')}
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12"></TableHead>
                  <TableHead>{t('clients.name')}</TableHead>
                  <TableHead>{t('clients.vpn_type')}</TableHead>
                  <TableHead>{t('clients.virtual_cidr')}</TableHead>
                  <TableHead>{t('clients.real_cidr')}</TableHead>
                  <TableHead>{t('clients.dns_server')}</TableHead>
                  <TableHead>{t('clients.tunnel_state')}</TableHead>
                  <TableHead className="text-right">{t('clients.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <StatusLed state={STATE_TO_LED[c.tunnel_state]} />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium text-foreground">{c.name}</span>
                        <span className="text-[11px] text-muted-foreground">{c.id}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="rounded-sm bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-primary">
                        {c.vpn_type}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {c.virtual_cidr}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {c.real_cidr}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {c.dns_server ?? '—'}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span
                          className={`text-xs font-medium ${
                            c.tunnel_state === 'errored'
                              ? 'text-[oklch(70%_0.18_25)]'
                              : c.tunnel_state === 'up'
                                ? 'text-[oklch(72%_0.16_160)]'
                                : ''
                          }`}
                        >
                          {t(`clients.states.${c.tunnel_state}`)}
                        </span>
                        {c.tunnel_state === 'errored' && c.tunnel_last_error && (
                          <Tooltip label={c.tunnel_last_error}>
                            <span className="mt-0.5 cursor-help truncate text-[10px] text-muted-foreground underline decoration-dotted">
                              {c.tunnel_last_error.length > 48
                                ? c.tunnel_last_error.slice(0, 48) + '…'
                                : c.tunnel_last_error}
                            </span>
                          </Tooltip>
                        )}
                        {c.tunnel_last_check_at && (
                          <span className="mt-0.5 font-mono text-[9px] text-muted-foreground/70">
                            check {new Date(c.tunnel_last_check_at).toLocaleTimeString()}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="space-x-1 text-right">
                      {c.tunnel_state === 'stopped' || c.tunnel_state === 'errored' ? (
                        <Tooltip label={t('clients.connect')}>
                          <Button
                            size="icon"
                            variant="ghost"
                            disabled={busyId === c.id}
                            onClick={() => connect(c.id)}
                          >
                            {busyId === c.id ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              <Power size={14} />
                            )}
                          </Button>
                        </Tooltip>
                      ) : (
                        <Tooltip label={t('clients.disconnect')}>
                          <Button
                            size="icon"
                            variant="ghost"
                            disabled={busyId === c.id}
                            onClick={() => disconnect(c.id)}
                          >
                            {busyId === c.id ? (
                              <Loader2 size={14} className="animate-spin" />
                            ) : (
                              <PowerOff size={14} />
                            )}
                          </Button>
                        </Tooltip>
                      )}
                      <Tooltip label={t('clients.logs')}>
                        <Button size="icon" variant="ghost" onClick={() => openLogs(c.id)}>
                          <FileText size={14} />
                        </Button>
                      </Tooltip>
                      <Tooltip label={t('common.edit')}>
                        <Button size="icon" variant="ghost" onClick={() => openEdit(c)}>
                          <Pencil size={14} />
                        </Button>
                      </Tooltip>
                      <Tooltip label={t('common.delete')}>
                        <Button size="icon" variant="ghost" onClick={() => remove(c.id)}>
                          <Trash2 size={14} />
                        </Button>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Modal
        open={showCreate}
        onClose={() => {
          setShowCreate(false);
          setForm(EMPTY_FORM);
          setError(null);
        }}
        title={t('clients.create')}
        description={t('clients.form_intro')}
        size="lg"
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setShowCreate(false);
                setForm(EMPTY_FORM);
              }}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" form="client-form">
              {t('clients.save')}
            </Button>
          </>
        }
      >
        <form id="client-form" onSubmit={submitNew} className="grid gap-4 md:grid-cols-2">
          <Field label={t('clients.id')} hint="usado em DNS · 3-32 caracteres">
            <Input
              required
              value={form.id}
              onChange={(e) => set('id', e.target.value)}
              placeholder="ex: petroleo"
            />
          </Field>
          <Field label={t('clients.name')}>
            <Input
              required
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="Petróleo SA"
            />
          </Field>
          <Field label={t('clients.vpn_type')}>
            <Select value={form.vpn_type} onChange={(e) => set('vpn_type', e.target.value as VpnType)}>
              {VPN_TYPES.map((p) => (
                <option key={p} value={p}>
                  {VPN_TYPE_LABEL[p]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('clients.dns_server')} hint="opcional">
            <Input
              value={form.dns_server}
              onChange={(e) => set('dns_server', e.target.value)}
              placeholder="172.16.0.10"
            />
          </Field>
          <Field label={t('clients.virtual_cidr')} hint="alocado automaticamente · só altere se precisar">
            <div className="flex gap-1">
              <Input
                required
                value={form.virtual_cidr}
                onChange={(e) => set('virtual_cidr', e.target.value)}
                placeholder="10.200.10.0/24"
              />
              <Button type="button" variant="outline" size="sm" onClick={fillAutoVirtual} title="próximo /24 livre">
                auto
              </Button>
            </div>
          </Field>
          <Field
            label={t('clients.real_cidr')}
            hint="opcional · deixe vazio que descobrimos ao conectar"
          >
            <Input
              value={form.real_cidr}
              onChange={(e) => set('real_cidr', e.target.value)}
              placeholder="vazio = auto-detectar via PPP/TUN ao conectar"
            />
          </Field>
          <Field
            label={t('clients.username')}
            required={form.auth_method === 'otp' || form.auth_method === 'saml'}
            hint={
              form.auth_method === 'saml'
                ? 'email/UPN do AD — precisa bater com o login Microsoft'
                : form.auth_method === 'otp'
                  ? 'usuário da VPN'
                  : undefined
            }
          >
            <Input
              value={form.vpn_username}
              onChange={(e) => set('vpn_username', e.target.value)}
              autoComplete="off"
              required={form.auth_method === 'otp' || form.auth_method === 'saml'}
            />
          </Field>
          <Field label={t('clients.password')} required={form.auth_method === 'otp'}>
            <Input
              type="password"
              value={form.vpn_password}
              onChange={(e) => set('vpn_password', e.target.value)}
              autoComplete="new-password"
              required={form.auth_method === 'otp'}
            />
          </Field>
          <div className="md:col-span-2 rounded-md border border-border bg-popover px-3 py-2.5 text-sm">
            <p className="mb-2 font-medium">Tipo de autenticação</p>
            <div className="space-y-2">
              {(
                [
                  {
                    v: 'none',
                    label: 'Sem MFA',
                    hint: 'só usuário e senha',
                  },
                  {
                    v: 'otp',
                    label: 'OTP — código do app autenticador',
                    hint: 'Microsoft Authenticator, Google Authenticator, etc. VAGG pede o código ao Conectar.',
                  },
                  {
                    v: 'saml',
                    label: 'SAML / SSO — login via browser',
                    hint: 'Microsoft, Google Workspace, Okta, etc. VAGG abre o login no browser ao Conectar.',
                  },
                ] as const
              ).map((opt) => (
                <label key={opt.v} className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="auth_method_create"
                    value={opt.v}
                    checked={form.auth_method === opt.v}
                    onChange={() => set('auth_method', opt.v)}
                    className="mt-0.5"
                  />
                  <div>
                    <p className="text-sm">{opt.label}</p>
                    <p className="text-[11px] text-muted-foreground">{opt.hint}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>
          {(form.vpn_type === 'openfortivpn' || form.vpn_type === 'globalprotect') && (
            <>
              <Field
                label="Gateway remoto"
                hint={
                  form.vpn_type === 'globalprotect'
                    ? 'endereço do portal/gateway GlobalProtect (sem https://)'
                    : 'endereço do FortiGate (sem https://)'
                }
              >
                <Input
                  value={form.forti_host}
                  onChange={(e) => set('forti_host', e.target.value)}
                  placeholder={
                    form.vpn_type === 'globalprotect'
                      ? 'ex: vpn.minerva.com.br'
                      : 'ex: vpn.empresa.com.br'
                  }
                />
              </Field>
              <Field
                label="Porta"
                hint={form.vpn_type === 'globalprotect' ? 'default 443' : 'default 10443'}
              >
                <Input
                  type="number"
                  value={form.forti_port}
                  onChange={(e) => set('forti_port', e.target.value)}
                  placeholder={form.vpn_type === 'globalprotect' ? '443' : '10443'}
                />
              </Field>
              {form.vpn_type === 'openfortivpn' && (
                <Field
                  label="Trusted cert SHA-256 (opcional)"
                  hint="vazio = aceita qualquer cert na 1ª conexão; pegue o hash dos logs depois"
                  className="md:col-span-2"
                >
                  <Input
                    value={form.forti_trusted_cert}
                    onChange={(e) => set('forti_trusted_cert', e.target.value)}
                    placeholder="ex: c2b1392f27fcdb413c63b51a42f04357ef64da3547c6713290575ba3ab0bc631"
                  />
                </Field>
              )}
            </>
          )}
          <Field
            label={
              form.vpn_type === 'openfortivpn'
                ? 'Configuração do túnel (gerada automaticamente — só edite se precisar)'
                : t('clients.config_text')
            }
            className="md:col-span-2"
          >
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".ovpn,.conf,.wg,.ipsec,text/plain"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void handleFileUpload(f);
                    e.target.value = '';
                  }}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Upload size={14} className="mr-1.5" />
                  Anexar arquivo (.ovpn / .conf)
                </Button>
                {uploadInfo && (
                  <span className="text-xs text-muted-foreground">{uploadInfo}</span>
                )}
              </div>
              <textarea
                className="min-h-32 w-full rounded-md border border-input bg-popover px-3 py-2 font-mono text-xs transition-colors focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                value={
                  form.vpn_type === 'openfortivpn' && !form.config_text && form.forti_host
                    ? buildFortiConfig(form.forti_host, form.forti_port, form.forti_trusted_cert)
                    : form.config_text
                }
                onChange={(e) => set('config_text', e.target.value)}
                placeholder={
                  form.vpn_type === 'openfortivpn'
                    ? '(preenchido automaticamente a partir dos campos acima)'
                    : 'anexe o arquivo acima ou cole aqui o conteúdo do .ovpn / .conf'
                }
              />
            </div>
          </Field>

          {error && (
            <div className="md:col-span-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
              {error}
            </div>
          )}
        </form>
      </Modal>

      {/* Modal de logs */}
      <Modal
        open={logsFor !== null}
        onClose={() => {
          setLogsFor(null);
          setLogsContent('');
        }}
        title={`Logs · ${logsFor ?? ''}`}
        description="Últimas 200 linhas do container do túnel"
        size="lg"
        footer={
          <>
            {logsFor && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => openLogs(logsFor)}
                disabled={logsLoading}
              >
                <RefreshCw size={14} className={`mr-1.5 ${logsLoading ? 'animate-spin' : ''}`} />
                {t('common.refresh')}
              </Button>
            )}
            <Button variant="default" size="sm" onClick={() => setLogsFor(null)}>
              {t('common.close')}
            </Button>
          </>
        }
      >
        {logsLoading ? (
          <pre className="max-h-[60vh] overflow-auto rounded-md border border-border bg-slate-950 p-3 font-mono text-[11px] leading-snug text-slate-100">
            carregando…
          </pre>
        ) : logsContent ? (
          <pre className="max-h-[60vh] overflow-auto rounded-md border border-border bg-slate-950 p-3 font-mono text-[11px] leading-snug text-slate-100">
            {logsContent}
          </pre>
        ) : (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-medium">Sem logs disponíveis ainda.</p>
            <p className="mt-1 text-xs">
              O cliente <strong>{logsFor}</strong> nunca foi conectado — o
              container do túnel ainda não existe. Feche este modal, clique no
              ícone <strong>⏻ Conectar</strong> na linha do cliente e tente
              novamente.
            </p>
          </div>
        )}
      </Modal>

      {/* Modal de edição */}
      <Modal
        open={editing !== null}
        onClose={() => {
          setEditing(null);
          setEditForm(null);
          setEditUploadInfo(null);
          setError(null);
        }}
        title={`Editar · ${editing?.name ?? ''}`}
        description="O ID e o protocolo não podem ser alterados após cadastro."
        size="lg"
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => {
                setEditing(null);
                setEditForm(null);
              }}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" form="client-edit-form">
              {t('common.save')}
            </Button>
          </>
        }
      >
        {editing && editForm && (
          <form id="client-edit-form" onSubmit={saveEdit} className="grid gap-4 md:grid-cols-2">
            {editLoading && (
              <div className="md:col-span-2 rounded-md border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="mr-1.5 inline-block animate-spin" />
                Carregando dados completos do cliente…
              </div>
            )}
            {/* Bloco de info read-only — não editável, mas dá contexto */}
            <div className="md:col-span-2 grid gap-2 rounded-md border border-border bg-secondary/40 px-3 py-2 text-xs sm:grid-cols-3">
              <div>
                <span className="font-medium text-muted-foreground">Estado: </span>
                <span className="font-medium text-foreground">
                  {t(`clients.states.${editing.tunnel_state}`)}
                </span>
              </div>
              <div>
                <span className="font-medium text-muted-foreground">Criado: </span>
                <span className="text-foreground">
                  {new Date(editing.created_at).toLocaleString()}
                </span>
              </div>
              <div>
                <span className="font-medium text-muted-foreground">Atualizado: </span>
                <span className="text-foreground">
                  {new Date(editing.updated_at).toLocaleString()}
                </span>
              </div>
            </div>
            <Field label={t('clients.id')} hint="imutável">
              <Input value={editing.id} disabled />
            </Field>
            <Field label={t('clients.vpn_type')} hint="imutável">
              <Input value={editing.vpn_type} disabled />
            </Field>
            <Field label={t('clients.name')}>
              <Input
                required
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              />
            </Field>
            <Field label="Descrição" hint="texto livre — nota interna do admin">
              <Input
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                placeholder="ex: VPN do projeto Athena · ativa até 2027-12"
              />
            </Field>
            <Field label={t('clients.dns_server')} hint="opcional">
              <Input
                value={editForm.dns_server}
                onChange={(e) => setEditForm({ ...editForm, dns_server: e.target.value })}
                placeholder="ex: 10.20.0.1"
              />
            </Field>
            <Field label={t('clients.virtual_cidr')}>
              <Input
                required
                value={editForm.virtual_cidr}
                onChange={(e) => setEditForm({ ...editForm, virtual_cidr: e.target.value })}
              />
            </Field>
            <Field label={t('clients.real_cidr')} hint="rede principal da VPN">
              <Input
                value={editForm.real_cidr}
                onChange={(e) => setEditForm({ ...editForm, real_cidr: e.target.value })}
                placeholder="vazio = auto-detectar"
              />
            </Field>
            <Field
              label="Redes adicionais"
              hint="recursos em outras LANs (SAP, datacenter, etc)"
              className="md:col-span-2"
            >
              <div className="flex flex-col gap-2">
                {editForm.extra_routes.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    Nenhuma rede adicional. Use o botão abaixo pra adicionar
                    sub-redes que existem além da rede principal da VPN.
                  </p>
                )}
                {editForm.extra_routes.map((route, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <Input
                      value={route}
                      onChange={(e) => {
                        const next = [...editForm.extra_routes];
                        next[idx] = e.target.value;
                        setEditForm({ ...editForm, extra_routes: next });
                      }}
                      placeholder="ex: 10.210.5.0/24"
                    />
                    <Tooltip label="remover">
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        onClick={() => {
                          const next = editForm.extra_routes.filter((_, i) => i !== idx);
                          setEditForm({ ...editForm, extra_routes: next });
                        }}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </Tooltip>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setEditForm({
                      ...editForm,
                      extra_routes: [...editForm.extra_routes, ''],
                    })
                  }
                  className="self-start"
                >
                  <Plus size={14} className="mr-1.5" />
                  Adicionar rede
                </Button>
              </div>
            </Field>
            {editing.vpn_type === 'openfortivpn' && (
              <>
                <Field label="Gateway remoto" className="md:col-span-2">
                  <Input
                    value={editForm.forti_host}
                    onChange={(e) => setEditForm({ ...editForm, forti_host: e.target.value })}
                    placeholder="ex: vpn.empresa.com.br"
                  />
                </Field>
                <Field label="Porta">
                  <Input
                    type="number"
                    value={editForm.forti_port}
                    onChange={(e) => setEditForm({ ...editForm, forti_port: e.target.value })}
                    placeholder="10443"
                  />
                </Field>
                <Field label="Trusted cert SHA-256" hint="vazio = aceitar qualquer cert">
                  <Input
                    value={editForm.forti_trusted_cert}
                    onChange={(e) =>
                      setEditForm({ ...editForm, forti_trusted_cert: e.target.value })
                    }
                    placeholder="cole o hash do cert pra fixar"
                  />
                </Field>
              </>
            )}
            <Field
              label={t('clients.username')}
              required={editForm.auth_method === 'otp' || editForm.auth_method === 'saml'}
              hint={
                editForm.auth_method === 'saml'
                  ? 'email/UPN do AD — precisa bater com o login Microsoft'
                  : editForm.auth_method === 'otp'
                    ? 'usuário da VPN'
                    : undefined
              }
            >
              <Input
                value={editForm.vpn_username}
                onChange={(e) => setEditForm({ ...editForm, vpn_username: e.target.value })}
                autoComplete="off"
                required={editForm.auth_method === 'otp' || editForm.auth_method === 'saml'}
              />
            </Field>
            <Field
              label={t('clients.password')}
              hint="vazio = manter atual"
              required={editForm.auth_method === 'otp'}
            >
              <Input
                type="password"
                value={editForm.vpn_password}
                onChange={(e) => setEditForm({ ...editForm, vpn_password: e.target.value })}
                placeholder="deixe vazio pra não alterar"
                autoComplete="new-password"
              />
            </Field>
            <div className="md:col-span-2 rounded-md border border-border bg-popover px-3 py-2.5 text-sm">
              <p className="mb-2 font-medium">Tipo de autenticação</p>
              <div className="space-y-2">
                {(
                  [
                    { v: 'none', label: 'Sem MFA', hint: 'só usuário e senha' },
                    {
                      v: 'otp',
                      label: 'OTP — código do app autenticador',
                      hint: 'Microsoft / Google Authenticator. Pede código ao Conectar.',
                    },
                    {
                      v: 'saml',
                      label: 'SAML / SSO — login via browser',
                      hint: 'Microsoft, Google, Okta. Abre o login no browser ao Conectar.',
                    },
                  ] as const
                ).map((opt) => (
                  <label key={opt.v} className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="auth_method_edit"
                      value={opt.v}
                      checked={editForm.auth_method === opt.v}
                      onChange={() => setEditForm({ ...editForm, auth_method: opt.v })}
                      className="mt-0.5"
                    />
                    <div>
                      <p className="text-sm">{opt.label}</p>
                      <p className="text-[11px] text-muted-foreground">{opt.hint}</p>
                    </div>
                  </label>
                ))}
              </div>
              {editForm.auth_method === 'saml' && editing.has_saml_cookie && (
                <p className="mt-2 text-[11px] text-[oklch(72%_0.16_160)]">
                  ✓ cookie SAML válido até{' '}
                  {editing.saml_cookie_expires_at
                    ? new Date(editing.saml_cookie_expires_at).toLocaleString()
                    : '—'}
                </p>
              )}
            </div>
            {(editing.vpn_type === 'globalprotect' || editing.vpn_type === 'openfortivpn') &&
              editForm.auth_method === 'saml' && (
              <div className="md:col-span-2 rounded-md border border-border bg-popover px-3 py-2.5 text-sm">
                <p className="font-medium">Status do cookie SAML</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {editing.has_saml_cookie ? (
                    <span className="text-[oklch(72%_0.16_160)]">
                      ✓ válido até{' '}
                      {editing.saml_cookie_expires_at
                        ? new Date(editing.saml_cookie_expires_at).toLocaleString()
                        : '—'}
                    </span>
                  ) : (
                    <span className="text-[oklch(78%_0.14_75)]">
                      sem cookie — vai pedir no Conectar
                    </span>
                  )}
                </p>

                {/* O fluxo SAML acontece automaticamente no botão Conectar
                    (modal pede prelogin → abre login → cola cookie → conecta).
                    Não precisa de bloco aqui. */}

                <p className="mt-2 text-[11px] text-muted-foreground">
                  Ao clicar <strong>Conectar</strong> na lista, o VAGG abre o
                  fluxo SSO (Microsoft/Google/Okta) numa nova aba e pede o
                  cookie pra concluir.
                </p>
                {editing.has_saml_cookie && (
                  <div className="mt-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        await Saml.clearCookie(editing.id);
                        toast.info('Cookie removido', 'Próximo Conectar vai pedir login.');
                        await list.refetch();
                      }}
                    >
                      Limpar cookie atual
                    </Button>
                  </div>
                )}
              </div>
            )}
            <Field
              label={`${t('clients.config_text')} (vazio = manter atual)`}
              className="md:col-span-2"
            >
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    ref={editFileRef}
                    type="file"
                    accept=".ovpn,.conf,.wg,.ipsec,text/plain"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void handleEditFileUpload(f);
                      e.target.value = '';
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => editFileRef.current?.click()}
                  >
                    <Upload size={14} className="mr-1.5" />
                    Substituir arquivo (opcional)
                  </Button>
                  {editUploadInfo && (
                    <span className="text-xs text-muted-foreground">{editUploadInfo}</span>
                  )}
                </div>
                <textarea
                  className="min-h-32 w-full rounded-md border border-input bg-popover px-3 py-2 font-mono text-xs transition-colors focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
                  value={editForm.config_text}
                  onChange={(e) => setEditForm({ ...editForm, config_text: e.target.value })}
                  placeholder="Deixe vazio pra manter o config atual. Cole/anexe arquivo apenas se quiser substituir."
                />
              </div>
            </Field>
            {error && (
              <div className="md:col-span-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
                {error}
              </div>
            )}
          </form>
        )}
      </Modal>

      {/* ── Modal OTP (MFA push token) ── */}
      <Modal
        open={!!otpModalFor}
        onClose={() => {
          if (!otpBusy) {
            setOtpModalFor(null);
            setOtpCode('');
          }
        }}
        title={otpModalFor ? `Conectar ${otpModalFor.name} · MFA` : ''}
        description="Esta VPN exige um código do app autenticador. Abra o Microsoft Authenticator (ou Google Authenticator) no seu celular e cole o código de 6 dígitos abaixo."
        footer={
          <>
            <Button
              variant="outline"
              onClick={() => {
                setOtpModalFor(null);
                setOtpCode('');
              }}
              disabled={otpBusy}
            >
              Cancelar
            </Button>
            <Button onClick={submitOtp} disabled={otpBusy || otpCode.length < 4}>
              {otpBusy ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : null}
              Conectar →
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Input
            type="text"
            inputMode="numeric"
            pattern="\d{4,8}"
            maxLength={8}
            value={otpCode}
            onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
            onKeyDown={(e) => e.key === 'Enter' && !otpBusy && otpCode.length >= 4 && submitOtp()}
            placeholder="000000"
            autoFocus
            className="text-center font-mono text-2xl tracking-[0.5em]"
          />
          <p className="text-[11px] text-muted-foreground">
            Tipicamente 6 dígitos. O código é entregue uma única vez ao container do
            túnel via canal seguro (não fica salvo).
          </p>
        </div>
      </Modal>

      {/* ── Modal SAML connect — browser remoto (saml-portal) em iframe.
          O container roda Firefox + mitmproxy no homelab, o user faz o login
          Microsoft DENTRO do iframe (iframe chama o noVNC do container) e o
          mitmproxy captura o cookie diretamente da resposta do gateway VPN.
          Polling automático: quando captured=true, dispara Connect e fecha. */}
      <Modal
        open={!!samlConnectFor}
        onClose={() => {
          if (!samlConnectBusy) closeSamlConnect();
        }}
        title={samlConnectFor ? `Conectar ${samlConnectFor.name} · SSO` : ''}
        description="Faça login Microsoft no painel abaixo. O cookie é capturado automaticamente e o túnel sobe sozinho."
        size="xl"
        footer={
          <>
            <Button variant="outline" onClick={closeSamlConnect} disabled={samlConnectBusy}>
              {samlConnectStatus === 'captured' ? 'Fechar' : 'Cancelar'}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="rounded-md border border-border bg-popover px-3 py-2 text-[11px] text-muted-foreground">
            {samlConnectStatus === 'starting' && (
              <span className="inline-flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" /> subindo browser remoto…
              </span>
            )}
            {samlConnectStatus === 'waiting' && (
              <span className="inline-flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin" />
                aguardando login Microsoft (cookie será capturado automaticamente)
              </span>
            )}
            {samlConnectStatus === 'captured' && (
              <span className="text-[oklch(72%_0.16_160)]">
                ✓ cookie capturado — túnel iniciando
              </span>
            )}
            {samlConnectStatus === 'error' && (
              <span className="text-[oklch(70%_0.18_25)]">
                ✗ {samlConnectError ?? 'erro desconhecido'}
              </span>
            )}
          </div>

          <div
            className="overflow-hidden rounded-md border border-border bg-black"
            style={{ aspectRatio: '16 / 10', minHeight: 460 }}
          >
            {samlPortalUrl ? (
              <iframe
                src={samlPortalUrl}
                title="VAGG SAML Portal"
                className="h-full w-full"
                style={{ border: 'none' }}
                allow="clipboard-read; clipboard-write"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
                {samlConnectStatus === 'starting' ? 'preparando portal…' : '—'}
              </div>
            )}
          </div>

          <p className="text-[10px] text-muted-foreground">
            Dica: este browser roda no servidor VAGG (não no seu PC). Por isso o
            cookie capturado aqui é válido pra subir o túnel — o gateway VPN
            associa a sessão ao IP do servidor, não ao seu.
          </p>
        </div>
      </Modal>

    </div>
  );
}

function Field({
  label,
  hint,
  className,
  required,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className={`flex flex-col gap-1.5 ${className ?? ''}`}>
      <span className="text-xs font-medium text-muted-foreground">
        {label}
        {required && <span className="ml-0.5 text-[oklch(70%_0.18_25)]">*</span>}
        {hint && <span className="ml-1.5 text-[10px] text-muted-foreground/70">· {hint}</span>}
      </span>
      {children}
    </label>
  );
}
