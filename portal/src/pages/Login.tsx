import { useState, type FormEvent } from 'react';
import { Portal } from '@/lib/api';

export function LoginPage() {
  const [email, setEmail] = useState('');
  const [clientId, setClientId] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await Portal.requestMagicLink(email, clientId);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="container">
      <div className="card">
        <h1>Portal de Transparência</h1>
        <p className="muted">
          Receba um link único por email. Ele expira em 15 minutos.
        </p>
        {submitted ? (
          <p>
            Se o email <strong>{email}</strong> está cadastrado para{' '}
            <strong>{clientId}</strong>, você receberá um link em alguns segundos.
          </p>
        ) : (
          <form onSubmit={submit}>
            <div style={{ marginBottom: 8 }}>
              <label htmlFor="email">Email</label>
              <br />
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={{ width: '100%' }}
              />
            </div>
            <div style={{ marginBottom: 12 }}>
              <label htmlFor="client_id">Cliente</label>
              <br />
              <input
                id="client_id"
                required
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                style={{ width: '100%' }}
                placeholder="petroleo"
              />
            </div>
            {error && <p className="err">{error}</p>}
            <button type="submit">Enviar link</button>
          </form>
        )}
      </div>
    </div>
  );
}
