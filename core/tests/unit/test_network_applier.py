"""Unit tests for NetworkApplier with a fake ``CommandRunner``.

We never call real subprocess commands; the runner is a callable that records
what would have been executed and returns canned results.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vagg_core.services.network_applier import (
    CommandResult,
    NetworkApplier,
    NetworkApplyError,
)
from vagg_core.services.network_plan import ClientNet, NatMappingSpec, build_plan

pytestmark = pytest.mark.asyncio


class FakeRunner:
    """Records every (argv, stdin) it sees; returns predetermined results."""

    def __init__(self, default: CommandResult | None = None) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self._default = default or CommandResult(0, "", "")
        self._responses: list[CommandResult] = []
        self._matchers: list[tuple[Callable[[list[str]], bool], CommandResult]] = []

    def respond(self, response: CommandResult) -> None:
        self._responses.append(response)

    def respond_to(self, predicate: Callable[[list[str]], bool], response: CommandResult) -> None:
        self._matchers.append((predicate, response))

    async def __call__(self, argv: list[str], *, stdin_data: str | None = None) -> CommandResult:
        self.calls.append((argv, stdin_data))
        for predicate, response in self._matchers:
            if predicate(argv):
                return response
        if self._responses:
            return self._responses.pop(0)
        return self._default


def _client(slug: str, *, virt: str, real: str) -> ClientNet:
    return ClientNet(
        id=slug,
        virtual_cidr=virt,
        real_cidr=real,
        nat_mappings=(NatMappingSpec(virtual_cidr=virt, real_cidr=real),),
    )


@pytest.fixture
def applier(tmp_path: Path) -> tuple[NetworkApplier, FakeRunner]:
    runner = FakeRunner()
    applier = NetworkApplier(runner=runner, rt_tables_path=tmp_path / "rt_tables")
    return applier, runner


class TestSysctls:
    async def test_skipped_when_already_at_desired_value(
        self, applier: tuple[NetworkApplier, FakeRunner]
    ) -> None:
        a, runner = applier
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        desired = dict(plan.sysctls)

        # Echo back the *correct* desired value for whichever sysctl key is
        # queried — so the applier sees "already there" and skips the write.
        async def echo_runner(argv: list[str], *, stdin_data: str | None = None) -> CommandResult:
            runner.calls.append((argv, stdin_data))
            if argv[:2] == ["sysctl", "-n"]:
                return CommandResult(0, f"{desired[argv[2]]}\n", "")
            return CommandResult(0, "", "")

        a._run = echo_runner  # type: ignore[assignment]
        await a.apply(plan)

        writes = [c for c in runner.calls if c[0][:2] == ["sysctl", "-w"]]
        assert writes == []

    async def test_writes_when_value_differs(
        self, applier: tuple[NetworkApplier, FakeRunner]
    ) -> None:
        a, runner = applier
        runner.respond_to(lambda argv: argv[:2] == ["sysctl", "-n"], CommandResult(0, "0\n", ""))
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        await a.apply(plan)
        writes = [c[0] for c in runner.calls if c[0][:2] == ["sysctl", "-w"]]
        assert ["sysctl", "-w", "net.ipv4.ip_forward=1"] in writes

    async def test_failure_raises_with_context(
        self, applier: tuple[NetworkApplier, FakeRunner]
    ) -> None:
        a, runner = applier
        runner.respond_to(lambda argv: argv[:2] == ["sysctl", "-n"], CommandResult(0, "0\n", ""))
        runner.respond_to(
            lambda argv: argv[:2] == ["sysctl", "-w"],
            CommandResult(1, "", "Operation not permitted"),
        )
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        with pytest.raises(NetworkApplyError):
            await a.apply(plan)

    async def test_permission_denied_is_soft_fail(
        self, applier: tuple[NetworkApplier, FakeRunner]
    ) -> None:
        """nf_conntrack_max requer SYS_ADMIN; com NET_ADMIN só, sysctl -w
        retorna 'permission denied'. Aplicar continua normal — só loga warning,
        já que sysctls são tuning, não correção."""
        a, runner = applier
        runner.respond_to(lambda argv: argv[:2] == ["sysctl", "-n"], CommandResult(0, "0\n", ""))
        runner.respond_to(
            lambda argv: argv[:2] == ["sysctl", "-w"],
            CommandResult(255, "", "sysctl: permission denied on key \"net.netfilter.nf_conntrack_max\""),
        )
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        # Não levanta — a sequência inteira (iptables, rules, routes) segue.
        await a.apply(plan)


class TestRtTables:
    async def test_writes_entries_to_disk(self, applier: tuple[NetworkApplier, FakeRunner]) -> None:
        a, runner = applier
        plan = build_plan(
            virtual_range="10.200.0.0/16",
            clients=[_client("petroleo", virt="10.200.1.0/24", real="192.168.1.0/24")],
        )
        await a.apply(plan)
        # rt_tables file should have been created
        rt_path = a._rt_tables_path
        content = rt_path.read_text(encoding="utf-8")
        assert "100 vagg-petroleo" in content

    async def test_idempotent(self, applier: tuple[NetworkApplier, FakeRunner]) -> None:
        a, _ = applier
        plan = build_plan(
            virtual_range="10.200.0.0/16",
            clients=[_client("petroleo", virt="10.200.1.0/24", real="192.168.1.0/24")],
        )
        await a.apply(plan)
        first = a._rt_tables_path.read_text(encoding="utf-8")
        await a.apply(plan)
        second = a._rt_tables_path.read_text(encoding="utf-8")
        assert first == second


class TestIptablesRestore:
    async def test_invokes_iptables_restore_with_plan(
        self, applier: tuple[NetworkApplier, FakeRunner]
    ) -> None:
        a, runner = applier
        plan = build_plan(
            virtual_range="10.200.0.0/16",
            clients=[_client("petroleo", virt="10.200.1.0/24", real="192.168.1.0/24")],
        )
        await a.apply(plan)
        ipt_calls = [c for c in runner.calls if c[0] == ["iptables-restore"]]
        assert len(ipt_calls) == 1
        argv, stdin_data = ipt_calls[0]
        assert stdin_data is not None
        assert "*nat" in stdin_data
        assert "10.200.1.0/24" in stdin_data

    async def test_iptables_failure_raises(
        self, applier: tuple[NetworkApplier, FakeRunner]
    ) -> None:
        a, runner = applier
        runner.respond_to(
            lambda argv: argv == ["iptables-restore"],
            CommandResult(2, "", "iptables: bad rule (does a matching rule exist?)"),
        )
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        with pytest.raises(NetworkApplyError):
            await a.apply(plan)


class TestIpRuleDiff:
    async def test_adds_missing_rules(self, applier: tuple[NetworkApplier, FakeRunner]) -> None:
        a, runner = applier
        # No current rules
        runner.respond_to(lambda argv: argv[:3] == ["ip", "-o", "rule"], CommandResult(0, "", ""))
        plan = build_plan(
            virtual_range="10.200.0.0/16",
            clients=[_client("petroleo", virt="10.200.1.0/24", real="192.168.1.0/24")],
        )
        await a.apply(plan)
        adds = [c[0] for c in runner.calls if c[0][:3] == ["ip", "rule", "add"]]
        assert ["ip", "rule", "add", "fwmark", "0x1", "table", "vagg-petroleo"] in adds

    async def test_removes_stale_vagg_rules(
        self, applier: tuple[NetworkApplier, FakeRunner]
    ) -> None:
        a, runner = applier
        runner.respond_to(
            lambda argv: argv[:3] == ["ip", "-o", "rule"],
            CommandResult(
                0,
                # Stale rule pointing at a deleted client
                "100: from all fwmark 0x9 lookup vagg-old-tenant\n",
                "",
            ),
        )
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        await a.apply(plan)
        dels = [c[0] for c in runner.calls if c[0][:3] == ["ip", "rule", "del"]]
        assert ["ip", "rule", "del", "fwmark", "0x9", "table", "vagg-old-tenant"] in dels

    async def test_ignores_non_vagg_rules(self, applier: tuple[NetworkApplier, FakeRunner]) -> None:
        a, runner = applier
        runner.respond_to(
            lambda argv: argv[:3] == ["ip", "-o", "rule"],
            CommandResult(
                0,
                "100: from all fwmark 0x100 lookup main\n",  # main is not vagg
                "",
            ),
        )
        plan = build_plan(virtual_range="10.200.0.0/16", clients=[])
        await a.apply(plan)
        dels = [c for c in runner.calls if c[0][:3] == ["ip", "rule", "del"]]
        assert dels == []


class TestApplyEndToEnd:
    async def test_full_apply_succeeds(self, applier: tuple[NetworkApplier, FakeRunner]) -> None:
        a, runner = applier
        # Defaults to returncode 0 for everything.
        plan = build_plan(
            virtual_range="10.200.0.0/16",
            clients=[
                _client("aaa", virt="10.200.1.0/24", real="192.168.1.0/24"),
                _client("bbb", virt="10.200.2.0/24", real="192.168.2.0/24"),
            ],
        )
        await a.apply(plan)
        # We don't assert exact set; just that a sufficient number of distinct
        # tools were invoked.
        seen_argv0 = {c[0][0] for c in runner.calls}
        assert {"sysctl", "iptables-restore", "ip"} <= seen_argv0


# Convenience: applier exposes _rt_tables_path for the tests above.
def _expose_path(_obj: Any) -> None: ...
