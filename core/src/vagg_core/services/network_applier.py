"""Apply a ``NetworkPlan`` to the host kernel (SPEC §4.2 + §4.3).

Production runs the applier on a Linux host with root + iptables + iproute2.
Tests inject a ``CommandRunner`` that captures invocations instead of executing
them, so unit tests run on any platform.

Atomicity:
  - iptables: a single ``iptables-restore`` syscall replaces the nat/mangle/
    filter tables atomically.
  - ip rule / ip route: diff-based — we read the current set, compute the
    required set, then add what's missing and remove what's stale.
  - sysctl / rt_tables: idempotent (skipped if already in desired state).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from vagg_core.core.errors import CoreError
from vagg_core.core.logging import get_logger
from vagg_core.services.network_plan import NetworkPlan

log = get_logger(__name__)


class NetworkApplyError(CoreError):
    code = "NETWORK_APPLY_ERROR"
    default_status = 500


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


# Async callable: ``(argv, *, stdin_data) -> CommandResult``.
CommandRunner = Callable[..., Awaitable[CommandResult]]


async def shell_runner(argv: list[str], *, stdin_data: str | None = None) -> CommandResult:
    """Real subprocess runner. Used in production; tests pass a fake."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdin_bytes = stdin_data.encode("utf-8") if stdin_data is not None else None
    stdout, stderr = await proc.communicate(input=stdin_bytes)
    return CommandResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


class NetworkApplier:
    """Apply a NetworkPlan via a ``CommandRunner``.

    ``rt_tables_path`` defaults to ``/etc/iproute2/rt_tables`` but tests can
    override to a tmp file.
    """

    _IP_RULE_FWMARK_RE = re.compile(r"from\s+all\s+fwmark\s+(0x[0-9a-fA-F]+)\s+lookup\s+(\S+)")

    def __init__(
        self,
        *,
        runner: CommandRunner,
        rt_tables_path: Path = Path("/etc/iproute2/rt_tables"),
    ) -> None:
        self._run = runner
        self._rt_tables_path = rt_tables_path

    async def apply(self, plan: NetworkPlan) -> None:
        """Apply the plan in the right order. Raises NetworkApplyError on failure."""
        await self._ensure_host_default_route()
        await self._apply_sysctls(plan)
        self._ensure_rt_tables(plan)
        await self._apply_iptables(plan)
        await self._reconcile_ip_rules(plan)
        await self._reconcile_ip_routes(plan)
        await self._apply_host_egress_strict()
        log.info(
            "network.apply.ok",
            clients=len(plan.iface_by_client),
            ip_rules=len(plan.ip_rules),
        )

    # ----- host default route self-heal -----

    # Quando todos os tunnels caem e o `default` do host era proveniente
    # de algum ppp/tun (raro mas acontece em homelabs onde o gateway natural
    # é também a internet via VPN), o host fica sem default route → tunnels
    # novos não conseguem alcançar gateway → falha em loop.
    # Self-heal: se o env VAGG_HOST_DEFAULT_GW está setado e o host não tem
    # default route, adiciona via $VAGG_HOST_DEFAULT_GW dev $VAGG_HOST_DEFAULT_DEV.
    # Idempotente (skip se já tem default). Default fallback: 192.168.68.1/ens18
    # (homelab Rodrigo). Override via env pra outros deploys.

    async def _ensure_host_default_route(self) -> None:
        """Se host não tem default route, adiciona via VAGG_HOST_DEFAULT_GW."""
        import os
        res = await self._run(["ip", "-o", "route", "show", "default"])
        if res.returncode == 0 and res.stdout.strip():
            return  # já tem default
        gw = os.getenv("VAGG_HOST_DEFAULT_GW", "192.168.68.1")
        dev = os.getenv("VAGG_HOST_DEFAULT_DEV", "ens18")
        add = await self._run(["ip", "route", "add", "default", "via", gw, "dev", dev])
        if add.returncode == 0:
            log.info("network.host_default_route.restored", gw=gw, dev=dev)
        else:
            log.warning(
                "network.host_default_route.add_failed",
                gw=gw, dev=dev, stderr=add.stderr.strip(),
            )

    # ----- host egress strict (anti-default-hijack) -----

    # Tabela de egress do host: pacotes pra IPs públicos (não-RFC1918) saem
    # SEMPRE via gateway natural ens18/eth0, NUNCA via ppp/tun de cliente.
    # Resolve o bug onde openfortivpn (ou outro daemon) sequestra o `default`
    # do host inteiro com `default dev pppN`. Detalhes em
    # `docs/screenshots/saml-flow/README.md` e memory `reference_vexia_saml`.
    _HOST_EGRESS_TABLE_ID = "100"
    _HOST_EGRESS_RULE_PRIO_RFC1918 = "200"
    _HOST_EGRESS_RULE_PRIO_DEFAULT = "300"

    async def _detect_host_gateway(self) -> tuple[str, str] | None:
        """Inspeciona o main table pra inferir o gateway natural do host
        (algo como ``via 192.168.68.1 dev ens18``). Retorna ``(gw_ip, iface)``
        ou None se não conseguir.

        Estratégia: procura uma rota ``X.X.X.X via Y.Y.Y.Y dev Z`` (que é
        adicionada pelo dhclient ou rota estática) e usa Y/Z como o gateway
        natural. Como fallback, procura no /etc/resolv.conf headers ou
        algum padrão conhecido.
        """
        res = await self._run(["ip", "-o", "route", "show", "table", "main"])
        if res.returncode != 0:
            return None
        # Procura primeiro: linha "X via GW dev IFACE" onde X é IP público
        # (não-RFC1918) — indica o gateway pra internet.
        import ipaddress
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                dst = parts[0]
                if dst == "default":
                    continue
                if "/" in dst:
                    net = ipaddress.ip_network(dst, strict=False)
                    if not net.is_global:
                        continue
                else:
                    if not ipaddress.ip_address(dst).is_global:
                        continue
            except ValueError:
                continue
            if "via" in parts and "dev" in parts:
                gw = parts[parts.index("via") + 1]
                iface = parts[parts.index("dev") + 1]
                return gw, iface
        return None

    async def _apply_host_egress_strict(self) -> None:
        """Configura policy routing strict pra que tráfego do host pra IPs
        públicos saia sempre via gateway natural, mesmo com `default dev pppN`
        no main table. Idempotente — re-rodar não duplica nada."""
        gw_info = await self._detect_host_gateway()
        if gw_info is None:
            log.debug("network.host_egress.no_gateway_detected — skipping strict policy")
            return
        gw, iface = gw_info
        tbl = self._HOST_EGRESS_TABLE_ID

        # Tabela 100: default via gw natural
        await self._run(["ip", "route", "flush", "table", tbl])
        add_route = await self._run(
            ["ip", "route", "add", "default", "via", gw, "dev", iface, "table", tbl]
        )
        if add_route.returncode != 0:
            log.warning(
                "network.host_egress.route_add_failed",
                table=tbl,
                gw=gw,
                iface=iface,
                stderr=add_route.stderr.strip(),
            )
            return

        # Limpa rules antigas (prioridades 200/300) — idempotência
        rules_res = await self._run(["ip", "-o", "rule", "list"])
        if rules_res.returncode == 0:
            for line in rules_res.stdout.splitlines():
                if line.startswith(("200:", "300:")):
                    prio = line.split(":", 1)[0]
                    await self._run(["ip", "rule", "del", "priority", prio])

        # RFC1918 → main (preserva acesso aos clientes via ppp/tun)
        for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
            res = await self._run([
                "ip", "rule", "add", "to", cidr, "lookup", "main",
                "priority", self._HOST_EGRESS_RULE_PRIO_RFC1918,
            ])
            if res.returncode != 0 and "exists" not in res.stderr.lower():
                log.warning(
                    "network.host_egress.rfc1918_rule_failed",
                    cidr=cidr,
                    stderr=res.stderr.strip(),
                )

        # 0/0 → tabela tbl (público sempre via gateway natural)
        res = await self._run([
            "ip", "rule", "add", "to", "0.0.0.0/0", "lookup", tbl,
            "priority", self._HOST_EGRESS_RULE_PRIO_DEFAULT,
        ])
        if res.returncode != 0 and "exists" not in res.stderr.lower():
            log.warning(
                "network.host_egress.default_rule_failed",
                table=tbl,
                stderr=res.stderr.strip(),
            )

        log.info(
            "network.host_egress.applied",
            table=tbl,
            gateway=gw,
            iface=iface,
        )

    # ----- sysctls -----

    async def _apply_sysctls(self, plan: NetworkPlan) -> None:
        """Aplica sysctls best-effort.

        Tuning, não correção: ``nf_conntrack_max`` etc afetam performance/limit
        mas o VAGG funciona sem eles. Se o container não tem cap pra escrever
        (ex: ``nf_conntrack_*`` precisa de SYS_ADMIN, não NET_ADMIN), só logamos
        warning. O admin do host pode setar via /etc/sysctl.d/ se precisar.
        """
        for key, value in plan.sysctls:
            current = await self._run(["sysctl", "-n", key])
            if current.returncode == 0 and current.stdout.strip() == value:
                continue
            res = await self._run(["sysctl", "-w", f"{key}={value}"])
            if res.returncode != 0:
                stderr = res.stderr.strip()
                if "permission denied" in stderr.lower():
                    log.warning(
                        "network.sysctl.skipped_no_perm",
                        key=key,
                        desired=value,
                        current=current.stdout.strip() if current.returncode == 0 else None,
                        hint="set via /etc/sysctl.d/99-vagg.conf on the host",
                    )
                    continue
                raise NetworkApplyError(
                    f"sysctl {key} falhou: {stderr}",
                    context={"key": key, "value": value},
                )

    # ----- rt_tables -----

    def _ensure_rt_tables(self, plan: NetworkPlan) -> None:
        """Idempotently write Vagg's table-IDs into /etc/iproute2/rt_tables.

        Drops any prior ``<id> vagg-...`` line (handles renames cleanly) and
        re-emits the desired set from ``plan.rt_tables``. Running twice with
        the same plan produces the exact same file content.

        Tolera PermissionError: o rt_tables é apenas pra friendly names das
        policy tables — ``ip rule add ... lookup 100`` funciona com ID numérico
        do mesmo jeito. Quando o container não tem perm pra escrever /etc
        (caso típico read-only fs ou usuário não-root), só logamos warning.
        Item §11.5 do MANUAL.md.
        """
        if not plan.rt_tables:
            return
        try:
            existing = self._rt_tables_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        except PermissionError:
            log.warning(
                "network.rt_tables.read_permission_denied",
                path=str(self._rt_tables_path),
                hint="aggregator running with restricted privileges; "
                "policy routing still works via numeric table IDs",
            )
            return
        kept = [line for line in existing.splitlines() if " vagg-" not in line]
        for table_id, name in plan.rt_tables:
            kept.append(f"{table_id} {name}")
        try:
            self._rt_tables_path.parent.mkdir(parents=True, exist_ok=True)
            self._rt_tables_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        except PermissionError:
            log.warning(
                "network.rt_tables.write_permission_denied",
                path=str(self._rt_tables_path),
                hint="run installer once to chown the file, or accept numeric IDs",
            )

    # ----- iptables-restore (atomic) -----

    async def _apply_iptables(self, plan: NetworkPlan) -> None:
        res = await self._run(["iptables-restore"], stdin_data=plan.iptables_restore_content)
        if res.returncode != 0:
            raise NetworkApplyError(
                f"iptables-restore falhou: {res.stderr.strip()}",
                context={"stdout": res.stdout, "stderr": res.stderr},
            )

    # ----- ip rule diff -----

    async def _reconcile_ip_rules(self, plan: NetworkPlan) -> None:
        res = await self._run(["ip", "-o", "rule", "list"])
        if res.returncode != 0:
            raise NetworkApplyError(f"ip rule list falhou: {res.stderr.strip()}")

        # Map current vagg rules: fwmark -> table
        current: dict[str, str] = {}
        for line in res.stdout.splitlines():
            match = self._IP_RULE_FWMARK_RE.search(line)
            if not match:
                continue
            mark, table = match.group(1).lower(), match.group(2)
            if table.startswith("vagg-"):
                current[mark] = table

        desired: dict[str, str] = {}
        for plan_text in plan.ip_rules:
            # Format: "fwmark 0x1 lookup vagg-petroleo"
            parts = plan_text.split()
            mark = parts[1].lower()
            table = parts[3]
            desired[mark] = table

        # Remove stale (in current but not desired, or different table)
        for mark, table in current.items():
            if desired.get(mark) != table:
                del_res = await self._run(["ip", "rule", "del", "fwmark", mark, "table", table])
                if del_res.returncode != 0:
                    log.warning(
                        "network.ip_rule_del_failed",
                        mark=mark,
                        table=table,
                        stderr=del_res.stderr.strip(),
                    )

        # Add missing
        for mark, table in desired.items():
            if current.get(mark) == table:
                continue
            add_res = await self._run(["ip", "rule", "add", "fwmark", mark, "table", table])
            if add_res.returncode != 0:
                raise NetworkApplyError(
                    f"ip rule add falhou: {add_res.stderr.strip()}",
                    context={"mark": mark, "table": table},
                )

    # ----- ip route diff (per table) -----

    async def _reconcile_ip_routes(self, plan: NetworkPlan) -> None:
        # Group desired routes by table.
        desired: dict[str, set[str]] = {}
        for rule_text in plan.ip_routes:
            # "default dev tun-xxx table vagg-petroleo"
            parts = rule_text.split()
            table = parts[-1]
            iface = parts[2]
            desired.setdefault(table, set()).add(f"default dev {iface}")

        # Also reset stale routes in tables we no longer use.
        all_vagg_tables = {name for _, name in plan.rt_tables}
        managed_tables = set(desired.keys()) | all_vagg_tables

        for table in managed_tables:
            res = await self._run(["ip", "route", "list", "table", table])
            current_lines = set()
            if res.returncode == 0:
                current_lines = {line.strip() for line in res.stdout.splitlines() if line.strip()}
            else:
                # ``ip route list table X`` prints to stderr if the table is empty/unknown.
                # We treat that as an empty current set and continue.
                pass

            # Add missing routes
            for desired_route in desired.get(table, set()):
                if not any(desired_route in line for line in current_lines):
                    add_res = await self._run(
                        ["ip", "route", "add", *desired_route.split(), "table", table]
                    )
                    if add_res.returncode != 0:
                        # Common case: iface doesn't exist yet (tunnel still starting).
                        log.warning(
                            "network.ip_route_add_failed",
                            table=table,
                            route=desired_route,
                            stderr=add_res.stderr.strip(),
                        )

            # Remove stale routes (any route in this vagg-* table that isn't desired)
            for line in current_lines:
                if not line.startswith("default "):
                    continue
                if any(line.startswith(d) for d in desired.get(table, set())):
                    continue
                del_args = ["ip", "route", "del", *line.split(), "table", table]
                del_res = await self._run(del_args)
                if del_res.returncode != 0:
                    log.warning(
                        "network.ip_route_del_failed",
                        table=table,
                        route=line,
                        stderr=del_res.stderr.strip(),
                    )
