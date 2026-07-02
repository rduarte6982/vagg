"""SSH runner pro homelab — autentica com senha + roda comandos.

Uso:
  python ssh-runner.py exec  "comando"          → executa, imprime stdout+stderr
  python ssh-runner.py sudo  "comando"          → roda via sudo -S (senha via stdin)
  python ssh-runner.py upload  src   dst        → SCP up
  python ssh-runner.py exec-stream "comando"    → streaming linha-a-linha

Lê senha de VAGG_HOST_PASSWORD ou (default) "vagg2026". A senha NUNCA aparece na
linha de comando remota: pro sudo, é alimentada pelo stdin do canal SSH.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import paramiko

# Windows console é cp1252 por default — força UTF-8 pra não crashear em ✓ etc.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("VAGG_HOST", "192.168.68.102")
USER = os.environ.get("VAGG_USER", "rodrigo")
PASSWORD = os.environ.get("VAGG_HOST_PASSWORD", "vagg2026")


def connect(*, retries: int = 6, backoff: float = 2.0) -> paramiko.SSHClient:
    # O homelab às vezes recusa conexões TCP intermitentemente (flapping pós-boot
    # / rate-limit). Retry com backoff em vez de falhar na primeira.
    import time

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(HOST, username=USER, password=PASSWORD, timeout=15, look_for_keys=False)
            return c
        except (paramiko.ssh_exception.NoValidConnectionsError, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff)
    assert last_exc is not None
    raise last_exc


def run_exec(cmd: str, *, stream: bool = False) -> int:
    c = connect()
    try:
        # get_pty pra ver progresso de comandos como docker compose build
        stdin, stdout, stderr = c.exec_command(cmd, get_pty=True, timeout=None)
        if stream:
            for line in iter(stdout.readline, ""):
                if not line:
                    break
                sys.stdout.write(line)
                sys.stdout.flush()
            err = stderr.read().decode("utf-8", errors="replace")
            if err.strip():
                sys.stderr.write(err)
        else:
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            sys.stdout.write(out)
            if err.strip():
                sys.stderr.write(err)
        rc = stdout.channel.recv_exit_status()
        return rc
    finally:
        c.close()


def run_sudo(cmd: str) -> int:
    """Roda `cmd` via `sudo -S`, alimentando a senha pelo stdin do canal SSH.

    A senha vem de PASSWORD (env/default), nunca da linha de comando — assim não
    vaza em logs/transcript. Usa `-p ''` pra suprimir o prompt e `bash -lc` pro
    comando rodar num shell completo.
    """
    c = connect()
    try:
        full = "sudo -S -p '' bash -lc " + shlex.quote(cmd)
        stdin, stdout, stderr = c.exec_command(full, get_pty=False, timeout=None)
        stdin.write(PASSWORD + "\n")
        stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        sys.stdout.write(out)
        if err.strip():
            sys.stderr.write(err)
        return stdout.channel.recv_exit_status()
    finally:
        c.close()


def upload(src: str, dst: str) -> int:
    c = connect()
    try:
        sftp = c.open_sftp()
        Path(src).resolve()  # raises se não existe
        sftp.put(src, dst)
        sftp.close()
        print(f"uploaded {src} -> {dst}")
        return 0
    finally:
        c.close()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    op = argv[1]
    if op == "exec":
        return run_exec(argv[2])
    if op == "sudo":
        return run_sudo(argv[2])
    if op == "exec-stream":
        return run_exec(argv[2], stream=True)
    if op == "upload":
        return upload(argv[2], argv[3])
    print(f"op desconhecida: {op}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
