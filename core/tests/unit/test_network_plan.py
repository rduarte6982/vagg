"""Unit tests for network_plan — pure planner (no IO)."""

from __future__ import annotations

from vagg_core.services.network_plan import (
    ClientNet,
    NatMappingSpec,
    build_plan,
    iface_name,
    rt_table_name,
)


def _client(slug: str, *, virt: str = "10.200.1.0/24", real: str = "192.168.1.0/24") -> ClientNet:
    return ClientNet(
        id=slug,
        virtual_cidr=virt,
        real_cidr=real,
        nat_mappings=(NatMappingSpec(virtual_cidr=virt, real_cidr=real),),
    )


class TestIfaceName:
    def test_is_deterministic(self) -> None:
        assert iface_name("petroleo") == iface_name("petroleo")

    def test_fits_15_chars(self) -> None:
        # Linux IFNAMSIZ is 16 (15 chars + NUL).
        for slug in ["a", "petroleo", "industria", "x" * 64]:
            assert len(iface_name(slug)) <= 15

    def test_starts_with_tun(self) -> None:
        assert iface_name("anything").startswith("tun-")

    def test_collisions_unlikely(self) -> None:
        names = {iface_name(f"tenant-{i}") for i in range(1000)}
        assert len(names) == 1000


class TestRtTableName:
    def test_format(self) -> None:
        assert rt_table_name("petroleo") == "vagg-petroleo"

    def test_truncated_to_30(self) -> None:
        long_id = "very-long-tenant-id-with-extra-suffix"
        assert len(rt_table_name(long_id)) <= 30


class TestBuildPlan:
    def test_empty(self) -> None:
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        assert plan.iface_by_client == {}
        assert plan.rt_tables == ()
        # Even with no clients, the iptables content must contain the table headers
        # and the default-deny FORWARD policy.
        assert "*nat" in plan.iptables_restore_content
        assert ":FORWARD DROP" in plan.iptables_restore_content
        assert "VAGG_DROP_NO_CLIENT" in plan.iptables_restore_content

    def test_single_client_full_plan(self) -> None:
        c = _client("petroleo", virt="10.200.1.0/24", real="192.168.1.0/24")
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[c])

        # Iface + fwmark + rt table all assigned
        iface = plan.iface_by_client["petroleo"]
        assert iface.startswith("tun-")
        assert len(iface) <= 15
        assert plan.fwmark_by_client["petroleo"] == 0x1
        assert plan.rt_tables[0] == (100, "vagg-petroleo")

        # iptables content has the NETMAP rules in both directions
        content = plan.iptables_restore_content
        assert "-A PREROUTING -d 10.200.1.0/24 -j NETMAP --to 192.168.1.0/24" in content
        assert (
            f"-A POSTROUTING -s 192.168.1.0/24 -o {iface} -j NETMAP --to 10.200.1.0/24"
        ) in content
        # mangle marker
        assert "-A PREROUTING -d 10.200.1.0/24 -j MARK --set-mark 0x1" in content
        # filter allow + log + default deny
        assert "-A FORWARD -d 10.200.1.0/24 -j ACCEPT" in content

        # ip rule + ip route texts
        assert plan.ip_rules == ("fwmark 0x1 lookup vagg-petroleo",)
        assert plan.ip_routes == (f"default dev {iface} table vagg-petroleo",)

    def test_two_clients_get_distinct_marks_and_tables(self) -> None:
        a = _client("aaa", virt="10.200.1.0/24", real="192.168.1.0/24")
        b = _client("bbb", virt="10.200.2.0/24", real="192.168.2.0/24")
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[a, b])

        # Sorted by id → aaa gets fwmark 0x1, bbb gets 0x2
        assert plan.fwmark_by_client == {"aaa": 0x1, "bbb": 0x2}
        assert {t for _, t in plan.rt_tables} == {"vagg-aaa", "vagg-bbb"}
        # No iface name collision
        assert plan.iface_by_client["aaa"] != plan.iface_by_client["bbb"]

    def test_input_order_does_not_matter(self) -> None:
        a = _client("aaa")
        b = _client("bbb", virt="10.200.2.0/24", real="192.168.2.0/24")
        plan_ab = build_plan(virtual_range="10.200.0.0/16", clients=[a, b])
        plan_ba = build_plan(virtual_range="10.200.0.0/16", clients=[b, a])
        # Sorted internally → identical output.
        assert plan_ab.iptables_restore_content == plan_ba.iptables_restore_content
        assert plan_ab.ip_rules == plan_ba.ip_rules

    def test_overlapping_real_cidrs_get_distinct_outbound_ifaces(self) -> None:
        # Two tenants with the SAME real CIDR but different virtual CIDRs —
        # this is the headline use case from SPEC §4.2.
        a = _client("aaa", virt="10.200.1.0/24", real="192.168.1.0/24")
        b = _client("bbb", virt="10.200.2.0/24", real="192.168.1.0/24")
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[a, b])
        content = plan.iptables_restore_content

        # SNAT on the way out is differentiated by `-o tun-<hash>`.
        iface_a = plan.iface_by_client["aaa"]
        iface_b = plan.iface_by_client["bbb"]
        assert (
            f"-A POSTROUTING -s 192.168.1.0/24 -o {iface_a} -j NETMAP --to 10.200.1.0/24"
        ) in content
        assert (
            f"-A POSTROUTING -s 192.168.1.0/24 -o {iface_b} -j NETMAP --to 10.200.2.0/24"
        ) in content


class TestSysctls:
    def test_includes_ip_forward_and_conntrack(self) -> None:
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        keys = {k for k, _ in plan.sysctls}
        assert "net.ipv4.ip_forward" in keys
        assert "net.netfilter.nf_conntrack_max" in keys

    def test_ip_forward_is_one(self) -> None:
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        for key, value in plan.sysctls:
            if key == "net.ipv4.ip_forward":
                assert value == "1"
                return
        raise AssertionError("ip_forward not found")
