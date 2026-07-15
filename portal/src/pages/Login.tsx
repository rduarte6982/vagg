import { useState, type FormEvent } from 'react';
import { Portal } from '@/lib/api';
import { isDemo } from '@/lib/demo';
import { useNavigate } from 'react-router-dom';
import { Shell } from '@/components/Shell';

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState(isDemo() ? 'auditor@cliente.com' : '');
  const [clientId, setClientId] = useState(isDemo() ? 'petroleo' : '');
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await Portal.requestMagicLink(email, clientId);
      if (isDemo()) {
        // em demo mode pulamos o magic link e vamos direto pra dashboard
        navigate('/dashboard', { replace: true });
        return;
      }
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell>
      <div className="brand-card">
        <h1>Acesso à transparência</h1>
        <p>
          O Portal mostra, para o cliente final, exatamente quem da
          consultoria acessou sua rede, quando e o que foi alcançado.
          A entrada é por <strong>magic link</strong> enviado ao seu e-mail
          autorizado.
        </p>
      </div>

      <div className="card">
        <div className="card__header">
          <h2>Solicitar link único</h2>
          <p className="muted">
            {isDemo()
              ? 'Modo demonstração — clique em "Acessar" para ir direto ao dashboard.'
              : 'O link expira em 15 minutos.'}
          </p>
        </div>
        <div className="card__body">
          {submitted ? (
            <p>
              Se o e-mail <strong>{email}</strong> está cadastrado para o
              cliente <strong>{clientId}</strong>, você receberá um link em
              alguns segundos.
            </p>
          ) : (
            <form onSubmit={submit}>
              <div className="field">
                <label htmlFor="email">E-mail autorizado</label>
                <input
                  id="email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                />
              </div>
              <div className="field">
                <label htmlFor="client_id">Identificador do cliente</label>
                <input
                  id="client_id"
                  required
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="ex: petroleo"
                />
              </div>
              {error && <p className="err">{error}</p>}
              <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
                <button type="submit" disabled={busy}>
                  {busy ? 'Enviando…' : isDemo() ? 'Acessar' : 'Enviar link'}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </Shell>
  );
}
