"""
KillSwitch guard and OOB-safe freeze plan helper.

WS14-009:
- reject blanket egress freeze commands that omit OOB allowlist
- generate deny-non-allowlist freeze plan with OOB exception

WS14-010:
- generate OOB health probe plan aligned with existing marker/allowlist policy
- validate probe plan shape before execution
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Iterable, List, Tuple


_UNSAFE_FREEZE_PATTERNS = (
    re.compile(r"(?is)\biptables\b[^\n]*\bOUTPUT\b[^\n]*\bDROP\b"),
    re.compile(r"(?is)\bnft\b[^\n]*\b(output|egress)\b[^\n]*\bdrop\b"),
)

_OOB_ALLOWLIST_MARKER = "OOB_ALLOWLIST_ENFORCED"
_OOB_HEALTH_PROBE_MARKER = "OOB_HEALTH_PROBE"


@dataclass(frozen=True)
class KillSwitchPlan:
    mode: str
    oob_allowlist: List[str]
    commands: List[str]


def validate_freeze_command(command: str) -> Tuple[bool, str]:
    text = (command or "").strip()
    if not text:
        return True, "empty command"

    for p in _UNSAFE_FREEZE_PATTERNS:
        if p.search(text):
            # Require explicit marker that OOB allowlist is enforced.
            if _OOB_ALLOWLIST_MARKER not in text:
                return False, "KillSwitch blocked: OUTPUT DROP without OOB allowlist marker"
    return True, "ok"


def _normalize_allowlist(oob_allowlist: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    for item in oob_allowlist:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            # Normalize IP/CIDR, keep hostname literals unchanged.
            normalized.append(str(ipaddress.ip_network(text, strict=False)))
        except Exception:
            normalized.append(text)
    dedup = sorted({x for x in normalized if x})
    return dedup


def _normalize_probe_targets(probe_targets: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    for item in probe_targets:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            normalized.append(str(ipaddress.ip_address(text)))
        except Exception:
            normalized.append(text)
    return sorted({x for x in normalized if x})


def _allowlist_entry_matches_target(allowlist_entry: str, probe_target: str) -> bool:
    try:
        target_ip = ipaddress.ip_address(probe_target)
    except Exception:
        target_ip = None

    try:
        allow_net = ipaddress.ip_network(allowlist_entry, strict=False)
    except Exception:
        allow_net = None

    if target_ip is not None and allow_net is not None:
        return target_ip in allow_net

    return allowlist_entry.strip().lower() == probe_target.strip().lower()


def _derive_probe_targets_from_allowlist(allowlist: Iterable[str]) -> List[str]:
    probe_targets: List[str] = []
    for entry in allowlist:
        text = str(entry or "").strip()
        if not text:
            continue
        try:
            net = ipaddress.ip_network(text, strict=False)
            # Only host CIDR entries can become direct probe targets safely.
            if net.prefixlen == net.max_prefixlen:
                probe_targets.append(str(net.network_address))
            continue
        except Exception:
            pass
        probe_targets.append(text)
    return sorted({x for x in probe_targets if x})


def _validate_probe_targets_for_allowlist(*, allowlist: List[str], probe_targets: Iterable[str]) -> List[str]:
    targets = _normalize_probe_targets(probe_targets)
    if not targets:
        raise ValueError("probe_targets is required")

    invalid_targets = [
        target
        for target in targets
        if not any(_allowlist_entry_matches_target(allow_item, target) for allow_item in allowlist)
    ]
    if invalid_targets:
        raise ValueError(
            "probe_targets not covered by oob_allowlist: "
            + ", ".join(sorted(invalid_targets))
        )
    return targets


def build_oob_killswitch_plan(
    *,
    oob_allowlist: Iterable[str],
    dns_allow: bool = True,
) -> KillSwitchPlan:
    allowlist = _normalize_allowlist(oob_allowlist)
    if not allowlist:
        raise ValueError("oob_allowlist is required")

    commands: List[str] = [
        f"# {_OOB_ALLOWLIST_MARKER}",
        "iptables -P OUTPUT DROP",
        "iptables -P INPUT DROP",
        "iptables -A INPUT -i lo -j ACCEPT",
        "iptables -A OUTPUT -o lo -j ACCEPT",
    ]
    if dns_allow:
        commands.extend(
            [
                "iptables -A OUTPUT -p udp --dport 53 -j ACCEPT",
                "iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT",
            ]
        )

    for target in allowlist:
        commands.append(f"iptables -A OUTPUT -d {target} -j ACCEPT")
        commands.append(f"iptables -A INPUT -s {target} -j ACCEPT")

    # Keep existing connections alive as a practical fallback.
    commands.append("iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT")
    commands.append("iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT")

    return KillSwitchPlan(
        mode="freeze_with_oob_allowlist",
        oob_allowlist=allowlist,
        commands=commands,
    )


def build_oob_health_probe_plan(
    *,
    oob_allowlist: Iterable[str],
    probe_targets: Iterable[str] | None = None,
    tcp_port: int = 22,
    ping_timeout_seconds: int = 2,
) -> KillSwitchPlan:
    allowlist = _normalize_allowlist(oob_allowlist)
    if not allowlist:
        raise ValueError("oob_allowlist is required")

    if tcp_port < 1 or tcp_port > 65535:
        raise ValueError("tcp_port must be in range [1, 65535]")

    if ping_timeout_seconds < 1 or ping_timeout_seconds > 30:
        raise ValueError("ping_timeout_seconds must be in range [1, 30]")

    if probe_targets is None:
        targets = _derive_probe_targets_from_allowlist(allowlist)
        if not targets:
            raise ValueError(
                "probe_targets is required when oob_allowlist contains CIDR ranges only"
            )
    else:
        targets = _validate_probe_targets_for_allowlist(
            allowlist=allowlist,
            probe_targets=probe_targets,
        )

    commands: List[str] = [
        f"# {_OOB_ALLOWLIST_MARKER}",
        f"# {_OOB_HEALTH_PROBE_MARKER}",
    ]
    for target in targets:
        commands.append(f"iptables -C OUTPUT -d {target} -j ACCEPT # {_OOB_ALLOWLIST_MARKER}")
        commands.append(f"iptables -C INPUT -s {target} -j ACCEPT # {_OOB_ALLOWLIST_MARKER}")
        commands.append(f"ping -c 1 -W {ping_timeout_seconds} {target}")
        commands.append(f"nc -z -w {ping_timeout_seconds} {target} {tcp_port}")

    return KillSwitchPlan(
        mode="oob_health_probe",
        oob_allowlist=allowlist,
        commands=commands,
    )


def validate_oob_health_probe_plan(
    *,
    oob_allowlist: Iterable[str],
    probe_targets: Iterable[str],
    commands: Iterable[str],
) -> Tuple[bool, str]:
    allowlist = _normalize_allowlist(oob_allowlist)
    if not allowlist:
        return False, "oob_allowlist is required"

    try:
        targets = _validate_probe_targets_for_allowlist(
            allowlist=allowlist,
            probe_targets=probe_targets,
        )
    except ValueError as exc:
        return False, str(exc)

    normalized_commands = [str(cmd or "").strip() for cmd in commands if str(cmd or "").strip()]
    if not normalized_commands:
        return False, "commands is required"

    text = "\n".join(normalized_commands)
    if _OOB_ALLOWLIST_MARKER not in text:
        return False, "probe plan missing OOB allowlist marker"
    if _OOB_HEALTH_PROBE_MARKER not in text:
        return False, "probe plan missing OOB health probe marker"

    for target in targets:
        output_rule = f"iptables -C OUTPUT -d {target} -j ACCEPT"
        input_rule = f"iptables -C INPUT -s {target} -j ACCEPT"
        if output_rule not in text or input_rule not in text:
            return False, f"probe plan missing allowlist check commands for target: {target}"

    return True, "ok"


__all__ = [
    "KillSwitchPlan",
    "validate_freeze_command",
    "build_oob_killswitch_plan",
    "build_oob_health_probe_plan",
    "validate_oob_health_probe_plan",
]
