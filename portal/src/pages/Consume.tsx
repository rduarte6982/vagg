import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Portal } from '@/lib/api';
import { Shell } from '@/components/Shell';

export function ConsumePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [requiresTotp, setRequiresTotp] = useState(false);
  const [code, setCode] = useState('');

  useEffect(() => {
    const token = params.get('token');
    if (!token) {
      setError('Token ausente no link.');
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
    <Shell>
      <div className="card">
        <div className="card__header">
          <h2>Validando seu acesso</h2>
          <p className="muted">
            {error
              ? 'Não foi possível validar o link.'
              : requiresTotp
                ? 'Confirmação adicional necessária.'
                : 'Aguarde…'}
          </p>
        </div>
        <div className="card__body">
          {error && <p className="err">{error}</p>}
          {!requiresTotp && !error && (
            <p>
              <span className="led led--warn" /> validando link…
            </p>
          )}
          {requiresTotp && (
            <form onSubmit={submitTotp}>
              <div className="field">
                <label htmlFor="totp">Código TOTP</label>
                <input
                  id="totp"
                  autoFocus
                  required
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  style={{ width: 160, letterSpacing: '0.4em', textAlign: 'center', fontSize: 18 }}
                />
              </div>
              <button type="submit">Entrar</button>
            </form>
          )}
        </div>
      </div>
    </Shell>
  );
}
