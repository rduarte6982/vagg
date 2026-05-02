import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Portal } from '@/lib/api';

export function ConsumePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [requiresTotp, setRequiresTotp] = useState(false);
  const [code, setCode] = useState('');

  useEffect(() => {
    const token = params.get('token');
    if (!token) {
      setError('token ausente');
      return;
    }
    Portal.consume(token)
      .then((r) => {
        if (r.requires_totp) {
          setRequiresTotp(true);
        } else {
          navigate('/dashboard', { replace: true });
        }
      })
      .catch((e: Error) => setError(e.message));
  }, [params, navigate]);

  const submitTotp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await Portal.postTotp(code);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="container">
      <div className="card">
        {error && <p className="err">{error}</p>}
        {!requiresTotp && !error && <p>Validando link…</p>}
        {requiresTotp && (
          <form onSubmit={submitTotp}>
            <h2>Código TOTP</h2>
            <p className="muted">Insira o código de 6 dígitos do seu app autenticador.</p>
            <input
              autoFocus
              required
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              style={{ width: 120, textAlign: 'center', fontSize: 18 }}
            />
            <button type="submit" style={{ marginLeft: 12 }}>
              Entrar
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
