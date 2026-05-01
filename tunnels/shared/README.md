# vagg-tunnel-controller

Componente compartilhado por todas as imagens `vagg/tunnel-*`. Roda dentro do container do túnel e expõe um unix socket de controle (SPEC §5.2).

## Protocolo (linha-a-linha JSON)

```
→ {"cmd": "status"}              ← {"ok": true, "state": "up", "uptime_s": 123}
→ {"cmd": "restart"}             ← {"ok": true}
→ {"cmd": "otp", "code": "123"}  ← {"ok": true}
unknown cmd                      ← {"ok": false, "error": "unknown_cmd"}
```

O `vagg-core` (host) é o consumidor; o controller dentro do container fala com o processo VPN específico (OpenVPN management interface, etc).

## Por que stdlib-only

A imagem alvo é Alpine, e instalar deps Python via pip lá custa MB e tempo de build. Nenhuma dep além da stdlib do Python 3.12.

## Dev

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
mypy --strict
pytest
```

## Suporte por protocolo

| Protocolo | Manager | Status |
|---|---|---|
| OpenVPN | `OpenVPNManager` | ✅ |
| OpenConnect (Cisco/GP) | a fazer | Fase 5 |
| OpenFortiVPN | a fazer | Fase 5 |
| WireGuard | a fazer | Fase 5 |
| strongSwan | a fazer | Fase 5 |
