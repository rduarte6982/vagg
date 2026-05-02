"""Pure renderer for the CoreDNS Corefile (SPEC §4.4 + §5.3).

Given the set of *connected* clients, returns a deterministic Corefile string.
Zero side effects — snapshot tests compare against golden output.

Each client becomes its own zone:

    {client-id}.vpn.{domain}:53 {{
        forward . {client.dns_server}:53 {{
            force_tcp
            bind {tun-iface}        # only when the iface is known to exist
            prefer_udp
        }}
        rewrite stop {{
            answer name regex (.*) {{1}}
            answer value regex {real_re} {virtual_prefix}.{{1}}
        }}
        cache 30
        log
    }}

The ``rewrite`` block remaps the answer's IP from the client's real CIDR onto
the virtual CIDR — that's how overlapping ranges get hidden behind unique
addresses on the consultor side.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DnsZoneSpec:
    """Per-client input to the renderer."""

    client_id: str
    real_cidr: str
    virtual_cidr: str
    dns_server: str | None
    iface: str | None  # ``None`` if the tunnel iface isn't up yet


_FORWARD_BLOCK = """\
    forward . {dns_server}:53 {{
{bind_line}\
        force_tcp
        prefer_udp
    }}
"""

_REWRITE_BLOCK = """\
    rewrite stop {{
        answer name regex (.*) {{1}}
        answer value regex {real_re} {virtual_prefix}.{{1}}
    }}
"""

_GLOBAL_BLOCK = """\
. {{
    forward . {forwarders}
    cache 30
}}
"""

_ZONE_TEMPLATE = """\
{zone_fqdn}:53 {{
{forward}\
{rewrite}\
    cache 30
    log
}}
"""


def render_corefile(
    *,
    domain: str,
    zones: Iterable[DnsZoneSpec],
    default_forwarders: Iterable[str] = ("8.8.8.8", "8.8.4.4"),
) -> str:
    """Return the full Corefile contents.

    ``domain`` is the consultancy's DNS suffix (SPEC §4.4 — e.g. the public
    ``vpn.consultoria.com.br``). Each zone is rendered as
    ``{client-id}.{domain}``.
    """
    blocks = [_GLOBAL_BLOCK.format(forwarders=" ".join(default_forwarders))]
    for zone in sorted(zones, key=lambda z: z.client_id):
        if not zone.dns_server:
            # SPEC §4.4: a client without a DNS server can't do split-horizon
            # — skip it. Forward zone is dropped; queries fall through to the
            # global ``.`` zone which will fail-NXDOMAIN, which is correct.
            continue
        blocks.append(
            _ZONE_TEMPLATE.format(
                zone_fqdn=f"{zone.client_id}.{domain}",
                forward=_render_forward(zone),
                rewrite=_render_rewrite(zone),
            )
        )
    return "\n".join(blocks)


def _render_forward(zone: DnsZoneSpec) -> str:
    bind_line = f"        bind {zone.iface}\n" if zone.iface else ""
    return _FORWARD_BLOCK.format(dns_server=zone.dns_server, bind_line=bind_line)


def _render_rewrite(zone: DnsZoneSpec) -> str:
    real_re = _cidr_to_regex(zone.real_cidr)
    virtual_prefix = _virtual_prefix(zone.virtual_cidr)
    return _REWRITE_BLOCK.format(real_re=real_re, virtual_prefix=virtual_prefix)


def _cidr_to_regex(cidr: str) -> str:
    """Build a regex that matches any IP inside ``cidr`` and captures the host octet.

    Only /24 CIDRs are supported in the rewrite block; broader subnets need
    a different rewrite shape. Raises ``ValueError`` on anything else so the
    caller surfaces config issues at write time.
    """
    network = ipaddress.IPv4Network(cidr, strict=False)
    if network.prefixlen != 24:
        raise ValueError(f"rewrite supports /24 only; got {cidr} (prefixlen {network.prefixlen})")
    a, b, c, _ = str(network.network_address).split(".")
    return rf"{re.escape(a)}\.{re.escape(b)}\.{re.escape(c)}\.(\d+)"


def _virtual_prefix(cidr: str) -> str:
    """Return ``a.b.c`` for a /24 virtual CIDR — the rewrite emits ``{prefix}.{1}``."""
    network = ipaddress.IPv4Network(cidr, strict=False)
    if network.prefixlen != 24:
        raise ValueError(f"virtual_cidr must be /24; got {cidr} (prefixlen {network.prefixlen})")
    a, b, c, _ = str(network.network_address).split(".")
    return f"{a}.{b}.{c}"
