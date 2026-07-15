/**
 * Modo demonstração do portal — quando `?demo=1` está na URL ou
 * VITE_DEMO=true, a chamada à API é desviada para um conjunto fixo de
 * dados em memória que simula um auditor consultando um cliente real.
 */

const FLAG_KEY = 'vagg.portal.demo';

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

export const PortalDemo = {
  requestMagicLink(_email: string, _clientId: string): void {
    /* no-op: o portal apenas mostra a tela de "enviado" */
  },
  consume(_token: string) {
    return {
      requires_totp: false,
      viewer_email: 'auditor@cliente.com',
      client_id: 'petroleo',
    };
  },
  postTotp(_code: string) {
    /* no-op */
  },
  dashboard(): Record<string, unknown> {
    return {
      client_id: 'petroleo',
      viewer_email: 'auditor@cliente.com',
      active_consultants: 2,
      connections: 14,
      denials: 0,
      generated_at: new Date().toISOString(),
    };
  },
  timeline(): Array<Record<string, unknown>> {
    const now = Date.now();
    return [
      {
        occurred_at: new Date(now - 60_000).toISOString(),
        event_type: 'tunnel.connect',
        scope_kind: 'full',
        scope_value_summary: '10.0.0.0/16',
      },
      {
        occurred_at: new Date(now - 5 * 60_000).toISOString(),
        event_type: 'auth.login.success',
        scope_kind: null,
        scope_value_summary: null,
      },
      {
        occurred_at: new Date(now - 60 * 60_000).toISOString(),
        event_type: 'policy.create',
        scope_kind: 'subnet',
        scope_value_summary: '10.10.5.0/24',
      },
    ];
  },
  reportsLgpd(): Blob {
    const txt =
      `Portal de Transparência — relatório de demonstração\n` +
      `gerado em ${new Date().toISOString()}\n` +
      `(no produto real este endpoint retorna um PDF assinado digitalmente)`;
    return new Blob([txt], { type: 'text/plain;charset=utf-8' });
  },
};
