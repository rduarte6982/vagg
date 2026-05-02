"""Unit tests for dns_render — pure Corefile renderer (no IO)."""

from __future__ import annotations

import pytest

from vagg_core.services.dns_render import DnsZoneSpec, render_corefile


def _zone(
    slug: str,
    *,
    real: str = "192.168.1.0/24",
    virt: str = "10.200.1.0/24",
    dns: str | None = "192.168.1.10",
    iface: str | None = "tun-abc123",
) -> DnsZoneSpec:
    return DnsZoneSpec(
        client_id=slug,
        real_cidr=real,
        virtual_cidr=virt,
        dns_server=dns,
        iface=iface,
    )


class TestRenderCorefile:
    def test_global_block_always_present(self) -> None:
        out = render_corefile(domain="vpn.consultoria.com.br", zones=[])
        assert ". {" in out
        assert "forward . 8.8.8.8 8.8.4.4" in out
        assert "cache 30" in out

    def test_zone_block_for_each_client(self) -> None:
        zones = [_zone("petroleo"), _zone("varejo", virt="10.200.2.0/24", real="192.168.2.0/24")]
        out = render_corefile(domain="vpn.consultoria.com.br", zones=zones)
        assert "petroleo.vpn.consultoria.com.br:53" in out
        assert "varejo.vpn.consultoria.com.br:53" in out

    def test_zones_are_sorted_deterministically(self) -> None:
        zones = [_zone("zzz"), _zone("aaa"), _zone("mmm")]
        out = render_corefile(domain="vpn.x.com.br", zones=zones)
        a = out.index("aaa.vpn.x.com.br")
        m = out.index("mmm.vpn.x.com.br")
        z = out.index("zzz.vpn.x.com.br")
        assert a < m < z

    def test_rewrite_block_uses_real_octets(self) -> None:
        out = render_corefile(domain="x.com", zones=[_zone("p", real="172.16.5.0/24")])
        # Three octets of the real network are baked into the regex.
        assert r"172\.16\.5\.(\d+)" in out

    def test_rewrite_emits_virtual_prefix(self) -> None:
        out = render_corefile(domain="x.com", zones=[_zone("p", virt="10.200.7.0/24")])
        assert "10.200.7.{1}" in out

    def test_skips_zone_without_dns_server(self) -> None:
        zones = [_zone("a"), _zone("b", dns=None)]
        out = render_corefile(domain="x.com", zones=zones)
        assert "a.x.com:53" in out
        assert "b.x.com:53" not in out

    def test_bind_only_when_iface_known(self) -> None:
        with_iface = render_corefile(domain="x.com", zones=[_zone("a", iface="tun-xx")])
        no_iface = render_corefile(domain="x.com", zones=[_zone("a", iface=None)])
        assert "bind tun-xx" in with_iface
        assert "bind" not in no_iface

    def test_real_cidr_must_be_slash_24(self) -> None:
        with pytest.raises(ValueError, match="rewrite supports /24 only"):
            render_corefile(domain="x.com", zones=[_zone("a", real="192.168.0.0/16")])

    def test_virtual_cidr_must_be_slash_24(self) -> None:
        with pytest.raises(ValueError, match="virtual_cidr must be /24"):
            render_corefile(domain="x.com", zones=[_zone("a", virt="10.200.0.0/16")])

    def test_custom_forwarders(self) -> None:
        out = render_corefile(
            domain="x.com",
            zones=[],
            default_forwarders=("1.1.1.1", "1.0.0.1"),
        )
        assert "forward . 1.1.1.1 1.0.0.1" in out

    def test_output_is_deterministic(self) -> None:
        zones = [_zone("a"), _zone("b", virt="10.200.2.0/24", real="192.168.2.0/24")]
        a = render_corefile(domain="x.com", zones=zones)
        b = render_corefile(domain="x.com", zones=zones)
        assert a == b
