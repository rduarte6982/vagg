"""Pure planner for the host's networking layer (SPEC §4.2 + §4.3).

Given the set of *connected* clients (with their tunnel iface, virtual_cidr,
real_cidr and NAT mappings), produces a ``NetworkPlan`` containing every shell
command and every iptables-restore line the applier needs to execute.

The planner has zero side effects — `build_plan` is a deterministic function
of its inputs. Snapshot tests compare its string output against a golden file.

Atomicity guarantees:
  - The *iptables* tables (nat / mangle / filter) are rewritten in a single
    iptables-restore syscall (kernel-atomic).
  - ``ip rule`` / ``ip route`` are applied as a diff (add missing, drop stale).
    There is a sub-millisecond window where a packet may match no rule; we
    accept that since the rebuild only happens on client lifecycle events.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field

# ----- Vagg-managed identifiers -----

# rt_tables IDs are allocated from this base. 100 is well clear of standard
# tables (local=255, main=254, default=253) and leaves room.
_RT_TABLE_BASE = 100
# Linux IFNAMSIZ is 16 (15 chars + NUL). We use 14: "tun-" + 10 hex chars.
_IFACE_PREFIX = "tun-"
_IFACE_HASH_LEN = 10
_FWMARK_BASE = 0x1


def iface_name(client_id: str) -> str:
    """Return the deterministic Linux iface name for a client (≤ 14 chars).

    SHA-1 is used as a non-cryptographic compressor (``usedforsecurity=False``):
    we need a short, stable mapping from arbitrary slug to a 10-hex-char tag.
    No auth or secret depends on this digest — collision resistance over a
    10-hex prefix is the only property that matters, and that's plenty.
    """
    digest = hashlib.sha1(  # noqa: S324 — non-crypto fingerprint
        client_id.encode("utf-8"), usedforsecurity=False
    ).hexdigest()[:_IFACE_HASH_LEN]
    return f"{_IFACE_PREFIX}{digest}"


def rt_table_name(client_id: str) -> str:
    """Routing-table label written into ``/etc/iproute2/rt_tables``."""
    # Truncate to 30 chars to stay well under iproute2 limits.
    return f"vagg-{client_id}"[:30]


# ----- Inputs -----


@dataclass(frozen=True, slots=True)
class NatMappingSpec:
    virtual_cidr: str
    real_cidr: str


@dataclass(frozen=True, slots=True)
class ClientNet:
    """Snapshot of a connected client used by the planner."""

    id: str
    virtual_cidr: str
    real_cidr: str
    nat_mappings: tuple[NatMappingSpec, ...]


# ----- Outputs -----


@dataclass(frozen=True, slots=True)
class NetworkPlan:
    """Everything the applier has to push down to the kernel."""

    virtual_range: str
    iptables_restore_content: str
    rt_tables: tuple[tuple[int, str], ...] = field(default_factory=tuple)
    ip_rules: tuple[str, ...] = field(default_factory=tuple)
    ip_routes: tuple[str, ...] = field(default_factory=tuple)
    sysctls: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    iface_by_client: dict[str, str] = field(default_factory=dict)
    fwmark_by_client: dict[str, int] = field(default_factory=dict)


# ----- Builder -----


def build_plan(*, virtual_range: str, clients: Iterable[ClientNet]) -> NetworkPlan:
    """Construct the full network plan for the given connected clients.

    Clients are sorted by id so that fwmarks/table-IDs are deterministic across
    rebuilds. Adding/removing a client *will* shift assignments — that's by
    design (we want the plan to be a pure function of the input set).
    """
    sorted_clients = sorted(clients, key=lambda c: c.id)

    iface_by_client: dict[str, str] = {}
    fwmark_by_client: dict[str, int] = {}
    rt_tables: list[tuple[int, str]] = []

    for idx, client in enumerate(sorted_clients):
        iface_by_client[client.id] = iface_name(client.id)
        fwmark_by_client[client.id] = _FWMARK_BASE + idx
        rt_tables.append((_RT_TABLE_BASE + idx, rt_table_name(client.id)))

    iptables = _build_iptables(
        virtual_range=virtual_range,
        clients=sorted_clients,
        iface_by_client=iface_by_client,
        fwmark_by_client=fwmark_by_client,
    )

    ip_rules = tuple(
        _format_ip_rule(fwmark=fwmark_by_client[c.id], table=rt_table_name(c.id))
        for c in sorted_clients
    )

    ip_routes = tuple(
        _format_ip_route(iface=iface_by_client[c.id], table=rt_table_name(c.id))
        for c in sorted_clients
    )

    sysctls = (
        ("net.ipv4.ip_forward", "1"),
        ("net.netfilter.nf_conntrack_max", "524288"),
        ("net.netfilter.nf_conntrack_tcp_timeout_established", "7200"),
    )

    return NetworkPlan(
        virtual_range=virtual_range,
        iptables_restore_content=iptables,
        rt_tables=tuple(rt_tables),
        ip_rules=ip_rules,
        ip_routes=ip_routes,
        sysctls=sysctls,
        iface_by_client=iface_by_client,
        fwmark_by_client=fwmark_by_client,
    )


def _format_ip_rule(*, fwmark: int, table: str) -> str:
    """Canonical text representation used for diffing against `ip rule list`."""
    return f"fwmark {fwmark:#x} lookup {table}"


def _format_ip_route(*, iface: str, table: str) -> str:
    """Canonical text representation used for diffing against `ip route list table T`."""
    return f"default dev {iface} table {table}"


# ----- iptables-restore content -----


def _build_iptables(
    *,
    virtual_range: str,
    clients: list[ClientNet],
    iface_by_client: dict[str, str],
    fwmark_by_client: dict[str, int],
) -> str:
    """Emit the full content suitable for ``iptables-restore``.

    Three tables: nat (NETMAP both ways), mangle (fwmark by destination),
    filter (default-deny FORWARD with explicit per-client ACCEPT + LOG).
    """
    nat_lines = ["*nat"]
    nat_lines += [
        ":PREROUTING ACCEPT [0:0]",
        ":INPUT ACCEPT [0:0]",
        ":OUTPUT ACCEPT [0:0]",
        ":POSTROUTING ACCEPT [0:0]",
    ]
    for client in clients:
        iface = iface_by_client[client.id]
        for mapping in client.nat_mappings:
            # Outbound: virtual → real (DNAT)
            nat_lines.append(
                f"-A PREROUTING -d {mapping.virtual_cidr} -j NETMAP --to {mapping.real_cidr}"
            )
            # Inbound (return): real → virtual (SNAT) only on the client's tun
            nat_lines.append(
                f"-A POSTROUTING -s {mapping.real_cidr} -o {iface} "
                f"-j NETMAP --to {mapping.virtual_cidr}"
            )
    nat_lines.append("COMMIT")

    mangle_lines = ["*mangle"]
    mangle_lines += [
        ":PREROUTING ACCEPT [0:0]",
        ":INPUT ACCEPT [0:0]",
        ":FORWARD ACCEPT [0:0]",
        ":OUTPUT ACCEPT [0:0]",
        ":POSTROUTING ACCEPT [0:0]",
    ]
    for client in clients:
        mark = fwmark_by_client[client.id]
        # Mark every packet bound for this client's virtual range.
        mangle_lines.append(f"-A PREROUTING -d {client.virtual_cidr} -j MARK --set-mark {mark:#x}")
    mangle_lines.append("COMMIT")

    filter_lines = ["*filter"]
    filter_lines += [
        ":INPUT ACCEPT [0:0]",
        ":FORWARD DROP [0:0]",  # default-deny (SPEC §7.3)
        ":OUTPUT ACCEPT [0:0]",
    ]
    # Established/related is always allowed.
    filter_lines.append("-A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT")
    # Per-client allow.
    for client in clients:
        filter_lines.append(f"-A FORWARD -d {client.virtual_cidr} -j ACCEPT")
    # Log everything else hitting the virtual range, then default-deny catches it.
    filter_lines.append(f'-A FORWARD -d {virtual_range} -j LOG --log-prefix "VAGG_DROP_NO_CLIENT "')
    filter_lines.append("COMMIT")

    return "\n".join(nat_lines + [""] + mangle_lines + [""] + filter_lines + [""])
