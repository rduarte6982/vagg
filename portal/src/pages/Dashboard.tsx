import { useEffect, useState } from 'react';
import { Portal } from '@/lib/api';

export function DashboardPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [timeline, setTimeline] = useState<Array<Record<string, unknown>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyReport, setBusyReport] = useState(false);

  useEffect(() => {
    Portal.dashboard().then(setData).catch((e: Error) => setError(e.message));
    Portal.timeline().then(setTimeline).catch(() => {});
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
    <div className="container">
      <div className="card">
        <h1>Portal de Transparência</h1>
        {error && <p className="err">{error}</p>}
        {data && (
          <>
            <p className="muted">
              Cliente: <strong>{String(data.client_id)}</strong> ·{' '}
              Auditor: <strong>{String(data.viewer_email)}</strong>
            </p>
            <ul>
              <li>
                Consultores ativos: <strong>{Number(data.active_consultants)}</strong>
              </li>
              <li>
                Conexões registradas: <strong>{Number(data.connections)}</strong>
              </li>
              <li>
                Acessos negados: <strong>{Number(data.denials)}</strong>
              </li>
            </ul>
            <button onClick={downloadReport} disabled={busyReport}>
              {busyReport ? 'Gerando PDF…' : 'Baixar relatório assinado (PDF)'}
            </button>
          </>
        )}
      </div>

      <div className="card">
        <h2>Timeline</h2>
        {!timeline && <p className="muted">Carregando…</p>}
        {timeline && timeline.length === 0 && <p className="muted">Sem eventos.</p>}
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
                  <td>{String(ev.occurred_at)}</td>
                  <td>{String(ev.event_type)}</td>
                  <td>
                    {ev.scope_kind ? `${String(ev.scope_kind)} ${String(ev.scope_value_summary ?? '')}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
