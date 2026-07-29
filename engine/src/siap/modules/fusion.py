"""Multi-Signal Fusion Engine (§6.5).

The proposal names fusion as its core contribution and never defines it. This is
the definition:

    A = max(A_zscore, A_iforest) * (1 + bonus * both_flagged)    capped at 1
    M = clip(|pct_change_7d| / momentum_scale, 0, 1)
    D = clip(demand_z52 / demand_scale, 0, 1)
    C = n_sources_flagging / n_sources_reporting

    F = 0.45*A + 0.25*M + 0.20*D + 0.10*C

Level assignment is not a pure function of F. `merah` additionally requires
corroboration: a single portal shouting on its own is not enough to tell a
warung owner to change what they buy. Where a commodity and region have only one
reporting source at all, the alert is capped at `kuning` and the reason recorded
— that is the honest answer when nothing can corroborate.

Every component is returned alongside the score. An alert a mentor cannot
decompose by hand is an alert that cannot be defended, so the breakdown is
stored rather than recomputed at render time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import FusionConfig

log = logging.getLogger(__name__)

LEVELS = ("hijau", "kuning", "merah")


@dataclass
class FusionInput:
    """Everything the score needs for one commodity x region x date."""

    norm_zscore: float | None = None
    norm_iforest: float | None = None
    zscore_flagged: bool = False
    iforest_flagged: bool = False
    pct_change_7d: float | None = None
    demand_z52: float | None = None
    n_sources_reporting: int = 0
    n_sources_flagging: int = 0
    # True when this commodity x region has only ever had one source, as opposed
    # to several sources of which only one reported today.
    single_source_coverage: bool = False


@dataclass
class FusionResult:
    score: float
    level: str
    components: dict[str, Any] = field(default_factory=dict)
    corroboration: float | None = None
    recommendation_id: str | None = None


def anomaly_term(inp: FusionInput, cfg: FusionConfig) -> tuple[float, bool]:
    """A = max(scores) * (1 + bonus if both flagged), capped at 1.

    The bonus is small because agreement is rare: M3 measured the two detectors
    overlapping on only 9.7% of flags, which is exactly why agreement is worth
    something.
    """
    scores = [s for s in (inp.norm_zscore, inp.norm_iforest) if s is not None]
    base = max(scores) if scores else 0.0
    both = bool(inp.zscore_flagged and inp.iforest_flagged)
    if both:
        base *= 1.0 + cfg.components.both_flagged_bonus
    return min(base, 1.0), both


def momentum_term(inp: FusionInput, cfg: FusionConfig) -> float:
    """M = clip(|pct_change_7d| / scale, 0, 1). Two-sided: a crash counts."""
    if inp.pct_change_7d is None:
        return 0.0
    return min(abs(inp.pct_change_7d) / cfg.components.momentum_scale, 1.0)


def demand_term(inp: FusionInput, cfg: FusionConfig) -> float:
    """D = clip(demand_z52 / scale, 0, 1).

    One-sided on purpose: falling search interest is not a reason to warn, so a
    negative z contributes 0 rather than a negative amount.

    Currently always 0 — Google Trends is throttled and `demand_signals` is
    empty. The absence is recorded on every alert rather than silently folded
    into the score.
    """
    if inp.demand_z52 is None:
        return 0.0
    return max(0.0, min(inp.demand_z52 / cfg.components.demand_scale, 1.0))


def corroboration_term(inp: FusionInput) -> float | None:
    """C = n_flagging / n_reporting, or None when nothing reported."""
    if inp.n_sources_reporting <= 0:
        return None
    return inp.n_sources_flagging / inp.n_sources_reporting


def assign_level(
    score: float, corroboration: float | None, inp: FusionInput, cfg: FusionConfig
) -> tuple[str, str | None]:
    """Map score to level, applying the corroboration rules. Returns (level, reason)."""
    if score < cfg.thresholds.kuning:
        return "hijau", None
    if score < cfg.thresholds.merah:
        return "kuning", None

    # Score qualifies for merah; now the corroboration gates. Three distinct
    # ways corroboration can be absent, each recorded separately so the reason
    # a merah was withheld is inspectable rather than inferred.
    if inp.single_source_coverage and cfg.corroboration.single_source_caps_at_kuning:
        # This commodity x region has only ever had one source. Nothing can
        # corroborate, today or ever.
        return "kuning", "single_source_coverage"
    if corroboration is None:
        return "kuning", "no_sources_reporting"
    if inp.n_sources_reporting < cfg.thresholds.merah_min_sources_reporting:
        # Several sources exist, but only one reported today — typically the
        # most recent day, before the slower portals publish. C would be 1/1
        # and read as unanimous agreement from a single voice.
        return "kuning", "single_source_reporting"
    if corroboration < cfg.thresholds.merah_min_corroboration:
        return "kuning", "insufficient_corroboration"
    return "merah", None


def fuse(inp: FusionInput, cfg: FusionConfig) -> FusionResult:
    """Compute F and the level, returning every component for inspection."""
    a, both = anomaly_term(inp, cfg)
    m = momentum_term(inp, cfg)
    d = demand_term(inp, cfg)
    c = corroboration_term(inp)

    w = cfg.weights
    score = w.anomaly * a + w.momentum * m + w.demand * d + w.corroboration * (c or 0.0)
    score = min(max(score, 0.0), 1.0)

    level, reason = assign_level(score, c, inp, cfg)

    components: dict[str, Any] = {
        "A": round(a, 6),
        "M": round(m, 6),
        "D": round(d, 6),
        "C": None if c is None else round(c, 6),
        "both_flagged": both,
        "n_sources_reporting": inp.n_sources_reporting,
        "n_sources_flagging": inp.n_sources_flagging,
        "norm_zscore": inp.norm_zscore,
        "norm_iforest": inp.norm_iforest,
        "pct_change_7d": inp.pct_change_7d,
        "demand_z52": inp.demand_z52,
        "demand_available": inp.demand_z52 is not None,
        "weights": {"A": w.anomaly, "M": w.momentum, "D": w.demand, "C": w.corroboration},
    }
    if reason:
        components["reason"] = reason

    return FusionResult(
        score=round(score, 6),
        level=level,
        components=components,
        corroboration=c,
        recommendation_id=cfg.recommendations.get(level),
    )


def explain(result: FusionResult, cfg: FusionConfig) -> str:
    """Render the arithmetic so a human can check it by hand — the M6 gate."""
    c = result.components
    w = cfg.weights
    lines = [
        f"  A = {c['A']:.6f}   x {w.anomaly}  = {w.anomaly * c['A']:.6f}",
        f"  M = {c['M']:.6f}   x {w.momentum}  = {w.momentum * c['M']:.6f}",
        f"  D = {c['D']:.6f}   x {w.demand}  = {w.demand * c['D']:.6f}",
    ]
    c_value = c["C"] if c["C"] is not None else 0.0
    lines.append(f"  C = {c_value:.6f}   x {w.corroboration}  = {w.corroboration * c_value:.6f}")
    lines.append(f"  {'':>24}F = {result.score:.6f}")
    lines.append(f"  level = {result.level}")
    if "reason" in c:
        lines.append(f"  downgraded: {c['reason']}")
    return "\n".join(lines)
