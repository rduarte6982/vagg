import { useEffect, useState } from 'react';
import {
  GetStatus,
  Login,
  Logout,
  SyncNow,
  ForceRefresh,
  GetServerURL,
  HideToTray,
  Reconnect,
  SubmitOTP,
} from '../wailsjs/go/main/App';
import { EventsOn } from '../wailsjs/runtime/runtime';
import { RefreshCw, LogOut, Loader2, Minimize2, RotateCw, Plug, KeyRound } from 'lucide-react';
import { VaggLogo, VaggMark } from './VaggLogo';

interface ClientItem {
  id: string;
  name: string;
  vpn_type: string;
  tunnel_state: string;
  routes: string[];
  auth_method?: string;
  requires_otp?: boolean;
  has_saml_cookie?: boolean;
  saml_cookie_valid?: boolean;
}

interface Status {
  connected: boolean;
  serverUrl: string;
  user: string;
  isAdmin: boolean;
  lastSync: string;
  routesActive: number;
  clients: ClientItem[] | null;
  serviceUp: boolean;
  lastError: string;
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loginVisible, setLoginVisible] = useState(false);
  const [serverUrl, setServerUrl] = useState('');
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  // Ações por linha (modelo híbrido): id do client em ação + inputs de OTP.
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const [otpInputs, setOtpInputs] = useState<Record<string, string>>({});

  useEffect(() => {
    refresh();
    const off = EventsOn('sync.ok', (s: Status) => {
      setStatus(s);
      // Sync OK = qualquer erro anterior (ex: token expirado que foi auto-recuperado
      // pelo refresh do backend) está resolvido. Limpa.
      setError(null);
    });
    const off2 = EventsOn('sync.error', (msg: string) => {
      // Erros 401 são auto-recuperáveis pelo refresh token — não polui a UI.
      // Backend tenta refresh + retry silenciosamente.
      if (/401|AUTH_REQUIRED|token.*inv.lid|token.*expir/i.test(msg)) {
        return;
      }
      setError(msg);
    });
    GetServerURL().then((u: string) => {
      if (u) setServerUrl(u);
    });
    return () => {
      off();
      off2();
    };
  }, []);

  const refresh = async () => {
    try {
      const s: Status = await GetStatus();
      setStatus(s);
      setLoginVisible(!s.connected);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleLogin = async () => {
    setBusy(true);
    setError(null);
    try {
      await Login(serverUrl, user, password);
      setPassword('');
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    await Logout();
    await refresh();
  };

  const handleSync = async () => {
    setBusy(true);
    setError(null);
    try {
      await SyncNow();
      await refresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleForceRefresh = async () => {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await ForceRefresh();
      await refresh();
      setInfo('Rotas removidas e recriadas com sucesso.');
      setTimeout(() => setInfo(null), 4000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleReconnect = async (id: string) => {
    setRowBusy(id);
    setError(null);
    setInfo(null);
    try {
      await Reconnect(id);
      await refresh();
      setInfo('Reconexão solicitada — aguarde o LED ficar verde.');
      setTimeout(() => setInfo(null), 4000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRowBusy(null);
    }
  };

  const handleOtp = async (id: string) => {
    const code = (otpInputs[id] ?? '').trim();
    if (!code) return;
    setRowBusy(id);
    setError(null);
    setInfo(null);
    try {
      await SubmitOTP(id, code);
      setOtpInputs((prev) => ({ ...prev, [id]: '' }));
      await refresh();
      setInfo('Código OTP enviado.');
      setTimeout(() => setInfo(null), 4000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRowBusy(null);
    }
  };

  if (!status || loginVisible) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-vagg-bg p-6">
        <div className="w-full max-w-md rounded-xl border border-vagg-line bg-vagg-bg-2 p-8 shadow-2xl">
          <div className="mb-7">
            <VaggLogo size={32} wordmarkSize="lg" />
            <p className="eyebrow mt-1.5 ml-12">client</p>
          </div>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-vagg-ink-3">
                URL do servidor
              </label>
              <input
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                placeholder="http://192.168.68.102"
                className="w-full rounded-md border border-vagg-line-2 bg-vagg-bg-3 px-3 py-2 text-sm text-vagg-ink placeholder:text-vagg-ink-4 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-vagg-ink-3">
                Usuário
              </label>
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                placeholder="rduarte"
                className="w-full rounded-md border border-vagg-line-2 bg-vagg-bg-3 px-3 py-2 text-sm text-vagg-ink placeholder:text-vagg-ink-4 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-vagg-ink-3">
                Senha
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
                className="w-full rounded-md border border-vagg-line-2 bg-vagg-bg-3 px-3 py-2 text-sm text-vagg-ink placeholder:text-vagg-ink-4 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
            {error && (
              <p className="rounded-md border border-vagg-crit/40 bg-vagg-crit/10 px-3 py-2 text-xs text-vagg-crit">
                {error}
              </p>
            )}
            <button
              onClick={handleLogin}
              disabled={busy || !serverUrl || !user || !password}
              className="w-full rounded-md bg-primary py-2 text-sm font-medium text-primary-ink hover:bg-primary-hover disabled:opacity-50"
            >
              {busy ? 'Entrando…' : 'Entrar'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  const clients = status.clients ?? [];

  return (
    <div className="min-h-screen bg-vagg-bg p-6 text-vagg-ink">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <VaggMark size={28} />
          <div>
            <p className="vagg-wordmark text-base">
              vagg<span className="dot">.</span>
              <span className="ml-1.5 text-xs font-normal text-vagg-ink-3">
                client
              </span>
            </p>
            <p className="text-[10px] uppercase tracking-[0.14em] text-vagg-ink-4 mt-0.5 font-mono">
              {status.user || 'usuário'}
              {status.isAdmin && (
                <span className="ml-1.5 text-primary">· admin</span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => HideToTray()}
            className="rounded-md border border-vagg-line-2 px-2.5 py-1.5 text-xs text-vagg-ink-2 hover:bg-vagg-bg-2"
            title="Minimizar para a bandeja"
          >
            <Minimize2 size={14} className="inline-block" />
          </button>
          <button
            onClick={handleLogout}
            className="rounded-md border border-vagg-line-2 px-2.5 py-1.5 text-xs text-vagg-ink-2 hover:bg-vagg-bg-2"
            title="Sair"
          >
            <LogOut size={14} className="inline-block" />
          </button>
        </div>
      </header>

      <div className="mb-4 rounded-lg border border-vagg-line bg-vagg-bg-2 p-4">
        <div className="mb-3 flex items-center gap-2">
          <span className={`led ${status.connected ? 'led-on' : 'led-error'}`} />
          <span className="text-sm font-medium">
            {status.connected ? 'Conectado ao servidor' : 'Desconectado'}
          </span>
          <span className="ml-1 text-[11px] text-vagg-ink-4 font-mono truncate">
            {status.serverUrl}
          </span>
          {!status.serviceUp && (
            <span
              className="ml-auto rounded-full border border-vagg-line-2 bg-vagg-bg-3 px-2 py-0.5 text-[11px] text-vagg-ink-3"
              title="O service que aplica rotas no Windows não está rodando — você ainda vê os clientes liberados, mas as rotas não são adicionadas. Reinstale o vagg-client ou inicie 'vagg-client-svc' nos Serviços do Windows."
            >
              ⓘ rotas não aplicadas (service)
            </span>
          )}
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-md bg-vagg-bg-3 border border-vagg-line p-2">
            <p className="text-vagg-ink-3 font-mono uppercase tracking-wide text-[10px]">
              Rotas ativas
            </p>
            <p className="text-base font-semibold mt-0.5">{status.routesActive}</p>
          </div>
          <div className="rounded-md bg-vagg-bg-3 border border-vagg-line p-2">
            <p className="text-vagg-ink-3 font-mono uppercase tracking-wide text-[10px]">
              Clientes
            </p>
            <p className="text-base font-semibold mt-0.5">{clients.length}</p>
          </div>
          <div className="rounded-md bg-vagg-bg-3 border border-vagg-line p-2">
            <p className="text-vagg-ink-3 font-mono uppercase tracking-wide text-[10px]">
              Última sync
            </p>
            <p className="truncate text-xs font-mono mt-0.5">
              {status.lastSync ? new Date(status.lastSync).toLocaleTimeString() : '—'}
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={handleSync}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-ink hover:bg-primary-hover disabled:opacity-50"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Sincronizar agora
          </button>
          <button
            onClick={handleForceRefresh}
            disabled={busy}
            title="Apaga todas as rotas do VAGG e recria. Use se algo parecer fora do lugar."
            className="inline-flex items-center gap-1.5 rounded-md border border-vagg-line-2 bg-transparent px-3 py-1.5 text-xs font-medium text-vagg-ink-2 hover:bg-vagg-bg-3 disabled:opacity-50"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <RotateCw size={12} />}
            Atualizar rotas
          </button>
        </div>
        {info && (
          <p className="mt-2 rounded-md border border-primary/30 bg-primary/10 px-3 py-2 text-[11px] text-primary">
            {info}
          </p>
        )}
      </div>

      <div className="rounded-lg border border-vagg-line bg-vagg-bg-2">
        <div className="border-b border-vagg-line px-4 py-2.5">
          <h2 className="text-sm font-semibold">Clientes liberados</h2>
          <p className="mt-0.5 text-[11px] text-vagg-ink-3">
            Os túneis sobem no servidor. Quando o LED estiver verde, você pode
            acessar a rede do cliente diretamente do seu Windows — sem abrir VPN local.
          </p>
        </div>
        <ul className="divide-y divide-vagg-line">
          {clients.length === 0 && (
            <li className="px-4 py-6 text-center text-xs text-vagg-ink-3">
              Você ainda não tem nenhum cliente liberado pelo administrador.
            </li>
          )}
          {clients.map((c) => {
            const led =
              c.tunnel_state === 'up'
                ? 'led-on'
                : c.tunnel_state === 'errored'
                  ? 'led-error'
                  : c.tunnel_state === 'starting'
                    ? 'led-warn'
                    : 'led-off';
            const stateLabel: Record<string, string> = {
              up: 'conectado',
              starting: 'conectando',
              down: 'desconectado',
              errored: 'erro',
              stopped: 'parado',
            };
            const rowLoading = rowBusy === c.id;
            const canReconnect =
              c.tunnel_state !== 'up' && c.tunnel_state !== 'starting';
            const showOtp =
              !!c.requires_otp &&
              (c.tunnel_state === 'starting' ||
                c.tunnel_state === 'down' ||
                c.tunnel_state === 'errored');
            const samlExpired =
              c.auth_method === 'saml' &&
              c.has_saml_cookie === true &&
              c.saml_cookie_valid === false;
            const samlMissing =
              c.auth_method === 'saml' && c.has_saml_cookie === false;
            return (
              <li key={c.id} className="px-4 py-3">
                <div className="flex items-center gap-3">
                  <span className={`led ${led}`} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{c.name}</p>
                    <p className="truncate font-mono text-[11px] text-vagg-ink-3">
                      {c.vpn_type} · {c.routes?.length ?? 0} rota(s)
                      {c.routes && c.routes.length > 0 && ' · ' + c.routes.slice(0, 2).join(', ')}
                      {c.routes && c.routes.length > 2 && ' (+' + (c.routes.length - 2) + ')'}
                    </p>
                  </div>
                  <span className="rounded-full border border-vagg-line bg-vagg-bg-3 px-2 py-0.5 font-mono text-[11px] text-vagg-ink-2">
                    {stateLabel[c.tunnel_state] ?? c.tunnel_state}
                  </span>
                  {canReconnect && (
                    <button
                      onClick={() => handleReconnect(c.id)}
                      disabled={rowLoading || busy}
                      title="Reconectar este túnel"
                      className="inline-flex items-center gap-1 rounded-md border border-vagg-line-2 px-2 py-1 text-[11px] font-medium text-vagg-ink-2 hover:bg-vagg-bg-3 disabled:opacity-50"
                    >
                      {rowLoading ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <Plug size={12} />
                      )}
                      Reconectar
                    </button>
                  )}
                </div>
                {showOtp && (
                  <div className="mt-2 ml-6 flex items-center gap-2">
                    <KeyRound size={13} className="text-vagg-ink-3" />
                    <input
                      value={otpInputs[c.id] ?? ''}
                      onChange={(e) =>
                        setOtpInputs((prev) => ({ ...prev, [c.id]: e.target.value }))
                      }
                      onKeyDown={(e) => e.key === 'Enter' && handleOtp(c.id)}
                      inputMode="numeric"
                      placeholder="código OTP"
                      className="w-32 rounded-md border border-vagg-line-2 bg-vagg-bg-3 px-2 py-1 font-mono text-xs text-vagg-ink placeholder:text-vagg-ink-4 focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                    <button
                      onClick={() => handleOtp(c.id)}
                      disabled={rowLoading || !(otpInputs[c.id] ?? '').trim()}
                      className="rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-primary-ink hover:bg-primary-hover disabled:opacity-50"
                    >
                      Enviar OTP
                    </button>
                  </div>
                )}
                {samlExpired && (
                  <p className="mt-2 ml-6 text-[11px] text-vagg-warn">
                    ⚠ Sessão SAML expirada — peça ao administrador para reautenticar este cliente.
                  </p>
                )}
                {samlMissing && (
                  <p className="mt-2 ml-6 text-[11px] text-vagg-ink-3">
                    ⓘ Este cliente usa SAML — o administrador precisa autenticar antes da conexão.
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-vagg-crit/40 bg-vagg-crit/10 px-3 py-2 text-xs text-vagg-crit">
          {error}
        </p>
      )}
    </div>
  );
}
