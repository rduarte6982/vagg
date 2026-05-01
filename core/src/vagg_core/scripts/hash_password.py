"""CLI: emit an argon2 hash of a password.

Used by the installer and by operators rotating the bootstrap admin password.
The hash goes into the ``VAGG_CORE_ADMIN_PASSWORD_HASH`` env var (SPEC §13.1).

Usage::

    python -m vagg_core.scripts.hash_password 'my-strong-password'
    # or with no arg, read from stdin (no echo not supported in pipe — use a file or env)
    echo 'my-strong-password' | python -m vagg_core.scripts.hash_password
"""

from __future__ import annotations

import sys

from vagg_core.core.security import hash_password


def main() -> int:
    if len(sys.argv) > 2:
        print("Usage: python -m vagg_core.scripts.hash_password [password]", file=sys.stderr)
        return 2
    password = sys.argv[1] if len(sys.argv) == 2 else sys.stdin.read().strip()
    if not password:
        print("ERROR: empty password", file=sys.stderr)
        return 2
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
