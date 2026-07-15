import { useEffect, useState } from 'react';
import { Portal } from '@/lib/api';
import { Shell } from '@/components/Shell';

export function DashboardPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [timeline, setTimeline] = useState<Array<Record<string, unknown>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyReport, setBusyReport] = useState(false);

  useEffect(() => {
    Portal.dashboard()
      .then(setData)
      .catch((e: Error) => setError(e.message));
    Portal.timeline()
      .then(setTimeline)
      .catch(() => {});
  }, []);

  const downloadReport = async () => {
    setBusyReport(true);
    try {
      const blob = await Portal.reportsLgpd();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `transparency-${new Date().toISOString().slice(0, 10)}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyReport(false);
    }
  };

  return (
    <Shell>
      <div className="brand-card">
        <h1>Olhar de dentro da sua rede</h1>
        <p>
          Estes números são gerados a partir do log de auditoria
          hash-chained do agregador. Você consegue exportar um relatório
          assinado a qualquer momento.
        </p>
      </div>

      <div className="card">
        <div className="card__header">
          <h2>Resumo</h2>
          {data ? (
            <p className="muted">
              Cliente <strong>{String(data.client_id)}</strong> · Auditor{' '}
              <strong>{String(data.viewer_email)}</strong>
            </p>
          ) : (
            <p className="muted">carregando…</p>
          )}
        </div>
        <div className="card__body">
          {error && <p className="err">{error}</p>}
          {data && (
            <>
              <div className="stat-grid">
                <div className="stat">
                  <div className="stat__label">Consultores ativos</div>
                  <div className="stat__value">{Number(data.active_consultants)}</div>
                </div>
                <div className="stat">
                  <div className="stat__label">Conexões registradas</div>
                  <div className="stat__value">{Number(data.connections)}</div>
                </div>
                <div className="stat">
                  <div className="stat__label">Acessos negados</div>
                  <div className="stat__value">{Number(data.denials)}</div>
                </div>
              </div>
              <div style={{ marginTop: 16 }}>
                <button onClick={downloadReport} disabled={busyReport}>
                  {busyReport ? 'Gerando PDF…' : 'Baixar relatório assinado (PDF)'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__header">
          <h2>Linha do tempo</h2>
          <p className="muted">Últimos eventos registrados pelo agregador.</p>
        </div>
        <div className="card__body" style={{ paddingTop: 0, paddingLeft: 0, paddingRight: 0 }}>
          {!timeline && <p className="muted" style={{ padding: '0 20px 16px' }}>carregando…</p>}
          {timeline && timeline.length === 0 && (
            <p className="muted" style={{ padding: '0 20px 16px' }}>Sem eventos.</p>
          )}
          {timeline && timeline.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Evento</th>
                  <th>Escopo</th>
                </tr>
              </thead>
              <tbody>
                {timeline.map((ev, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: 'monospace', fontSize: 11 }}>
                      {new Date(String(ev.occurred_at)).toLocaleString()}
                    </td>
                    <td>
                      <span className="led" />
                      {String(ev.event_type)}
                    </td>
                    <td>
                      {ev.scope_kind ? (
                        <span className="pill">
                          {String(ev.scope_kind)}
                          {ev.scope_value_summary
                            ? ` · ${String(ev.scope_value_summary)}`
                            : ''}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </Shell>
  );
}
