"""Parameter sensitivity for the paper (§7.5).

Three sweeps are asked for: IsolationForest contamination, the fusion weights,
and k against silhouette. Only one of the three can be answered fully today, and
saying which is the point of this module.

### Two kinds of question, and only one of them needs labels

**How the system's output moves when a parameter moves** — how many days get
flagged, how much the flag sets overlap, whether the alert ranking is stable
under a weight nudge, how silhouette varies with k. These are properties of the
model and the data. They need no ground truth and they run now.

**Whether the output gets better** — precision, recall, F1 against adjudicated
events. This needs two annotators to have finished. It is not computed here, and
`siap ablate` refuses rather than estimating it.

The distinction matters because the second question is the one the paper's claim
rests on, and a sensitivity table is easy to mistake for an accuracy table. A
contamination of 0.05 flagging more days than 0.03 is arithmetic, not evidence
that 0.05 is better.

### What a stable ranking does and does not tell you

The weight sweep reports Spearman correlation between the baseline score and the
perturbed score, plus how many alerts change level. High correlation means the
conclusion is not balanced on a knife edge — a reviewer's "why 0.45?" is
answered by "0.35 and 0.55 rank the same days". It does not mean the weights are
right. A model can be robustly wrong.

### Perturbation arithmetic

Fusion weights must sum to 1, so moving one by +/-0.1 requires the other three to
absorb the difference. They are rescaled proportionally, which preserves their
ratios to each other and isolates the change to the single weight under test. A
weight that would leave the range [0, 1] is skipped and reported as skipped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..config import AnalysisConfig, FusionConfig, FusionWeights, load_analysis, load_fusion
from ..db import Conn, fetch_all
from ..modules import fusion as fusion_module
from ..modules import iforest, kmeans

log = logging.getLogger(__name__)

CONTAMINATION_GRID = (0.01, 0.03, 0.05)
WEIGHT_DELTAS = (-0.10, 0.10)
WEIGHT_NAMES = ("anomaly", "momentum", "demand", "corroboration")


# ---------------------------------------------------------------------------
# k vs silhouette
# ---------------------------------------------------------------------------
@dataclass
class KCurvePoint:
    k: int
    inertia: float
    silhouette: float
    selected: bool
    eligible: bool


def k_curve(conn: Conn, cfg: AnalysisConfig) -> list[KCurvePoint]:
    """Silhouette across the whole k range, including the k that cannot be chosen.

    k=2 is fitted and reported even though `k_select_min` forbids selecting it.
    Hiding the point that scores best would be the kind of omission that makes a
    figure an argument rather than a measurement — and the reason k=2 is
    excluded is editorial (two clusters cannot fill a three-zone output), not
    statistical, so the reader is entitled to see the cost.
    """
    from ..cluster import load_cells

    daily = load_cells(conn, cfg)
    cells = kmeans.build_cells(daily, cfg.kmeans)
    if cells.empty:
        return []

    model = kmeans.fit(cells, cfg.kmeans, cfg.seed)
    return [
        KCurvePoint(
            k=entry.k,
            inertia=entry.inertia,
            silhouette=entry.silhouette,
            selected=entry.k == model.k_selected,
            eligible=entry.k >= cfg.kmeans.k_select_min,
        )
        for entry in model.k_search
    ]


# ---------------------------------------------------------------------------
# contamination
# ---------------------------------------------------------------------------
@dataclass
class ContaminationPoint:
    contamination: float
    series_scored: int
    days_scored: int
    days_flagged: int
    flag_rate: float
    jaccard_vs_baseline: float
    is_baseline: bool
    # True when every day this setting flags is also flagged by the next larger
    # contamination. Measured rather than assumed — see `nesting_note`.
    nested_in_next: bool | None = None


def contamination_sweep(
    conn: Conn, cfg: AnalysisConfig, grid: tuple[float, ...] = CONTAMINATION_GRID
) -> list[ContaminationPoint]:
    """Refit IsolationForest at each contamination and compare the flag sets.

    Jaccard against the configured baseline answers the question a reader
    actually has: does turning this knob find *different* days, or the same days
    plus a margin? Those have very different implications for a warung owner who
    only has attention for a handful of alerts.
    """
    from ..analyze import load_demand, load_series

    series_keys = fetch_all(
        conn,
        """
        select distinct u.commodity_id, u.region_id, rg.level as region_level
          from public.price_daily_unified u
          join public.regions rg on rg.id = u.region_id
         where u.price_median is not null
         order by u.commodity_id, u.region_id
        """,
    )

    flag_sets: dict[float, set[tuple[int, int, Any]]] = {c: set() for c in grid}
    scored_days = dict.fromkeys(grid, 0)
    scored_series = dict.fromkeys(grid, 0)

    for key in series_keys:
        commodity_id, region_id = int(key["commodity_id"]), int(key["region_id"])
        frame = load_series(conn, commodity_id, region_id, cfg.input.exclude_imputed)
        if frame.empty:
            continue
        demand = load_demand(conn, commodity_id, str(key["region_level"]))

        for contamination in grid:
            params = cfg.iforest.model_copy(update={"contamination": contamination})
            scored = iforest.compute(frame, params, cfg.seed, demand)
            if scored.empty or scored["raw_score"].isna().all():
                continue
            scored_series[contamination] += 1
            usable = scored[scored["raw_score"].notna()]
            scored_days[contamination] += len(usable)
            for obs_date in usable.loc[usable["is_flagged"], "obs_date"]:
                flag_sets[contamination].add((commodity_id, region_id, obs_date))

    baseline = cfg.iforest.contamination
    baseline_set = flag_sets.get(baseline, set())

    points: list[ContaminationPoint] = []
    for contamination in grid:
        flags = flag_sets[contamination]
        union = baseline_set | flags
        points.append(
            ContaminationPoint(
                contamination=contamination,
                series_scored=scored_series[contamination],
                days_scored=scored_days[contamination],
                days_flagged=len(flags),
                flag_rate=len(flags) / scored_days[contamination]
                if scored_days[contamination]
                else 0.0,
                jaccard_vs_baseline=len(baseline_set & flags) / len(union) if union else 1.0,
                is_baseline=contamination == baseline,
            )
        )

    # Is a larger contamination the same days plus more, or different days?
    # sklearn sets `offset_` as a quantile of one score distribution, so nesting
    # is expected — but "expected" is not "checked", and if it ever failed the
    # sweep would mean something entirely different.
    ordered = sorted(grid)
    for point, larger in zip(points, ordered[1:], strict=False):
        point.nested_in_next = flag_sets[point.contamination] <= flag_sets[larger]
    return points


def nesting_note(points: list[ContaminationPoint]) -> str:
    """One sentence on what the contamination sweep actually demonstrated."""
    checked = [p for p in points if p.nested_in_next is not None]
    if not checked:
        return ""
    if all(p.nested_in_next for p in checked):
        return (
            "Every flag set is a strict subset of the next larger one, so contamination "
            "does not change which days rank as unusual — only how far down the ranking "
            "the cut is made. Choosing 0.03 is therefore a decision about how many alerts "
            "a warung owner can attend to, not a modelling decision."
        )
    return (
        "The flag sets are NOT nested: some days flagged at a lower contamination are "
        "dropped at a higher one. That would mean the score ordering itself changes with "
        "the parameter, and the sweep needs re-reading before anything is concluded from it."
    )


# ---------------------------------------------------------------------------
# fusion weights
# ---------------------------------------------------------------------------
@dataclass
class WeightPoint:
    weight: str
    delta: float
    value: float
    skipped: str | None
    spearman: float = 0.0
    level_changes: int = 0
    n_scored: int = 0
    siaga: int = 0
    waspada: int = 0
    tenang: int = 0
    belum_dapat_dinilai: int = 0
    # Set when the term this weight multiplies never varies, which makes a
    # perfect Spearman meaningless.
    inert_because: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped is None


def _perturbed(weights: FusionWeights, name: str, delta: float) -> FusionWeights | None:
    """Move one weight, rescale the rest proportionally to restore the sum to 1."""
    current = dict(weights.model_dump())
    target = current[name] + delta
    if target < 0.0 or target > 1.0:
        return None

    others = [k for k in WEIGHT_NAMES if k != name]
    remaining = sum(current[k] for k in others)
    if remaining <= 0:
        return None

    scale = (1.0 - target) / remaining
    updated = {name: target, **{k: current[k] * scale for k in others}}
    # Absorb float drift into the largest of the rescaled weights so the
    # sum-to-1 validator cannot reject a perturbation for a 1e-17 residue.
    drift = 1.0 - sum(updated.values())
    largest = max(others, key=lambda k: updated[k])
    updated[largest] += drift
    return FusionWeights(**updated)


def weight_sensitivity(
    conn: Conn,
    anomaly_run_id: int,
    cfg: FusionConfig,
    deltas: tuple[float, ...] = WEIGHT_DELTAS,
) -> tuple[list[WeightPoint], WeightPoint]:
    """Rescore every fused day under each perturbed weight vector.

    Returns the perturbations and the unperturbed baseline, so a table can show
    what moved relative to what.
    """
    from ..fuse import load_inputs, to_input

    rows = load_inputs(conn, anomaly_run_id, cfg)
    inputs = [to_input(row) for row in rows]
    if not inputs:
        raise ValueError(
            "no fusion inputs for this anomaly run; run `siap analyze` and `siap fuse` first"
        )

    baseline_results = [fusion_module.fuse(inp, cfg) for inp in inputs]
    baseline_levels = [r.level for r in baseline_results]

    # Rows the detectors could not score have no F under any weight vector, so
    # they cannot participate in a rank correlation between weight vectors.
    # Which rows those are does not depend on the weights — A is missing or it
    # is not — so one mask, computed once, applies to every perturbation.
    scored = [i for i, r in enumerate(baseline_results) if r.score is not None]
    if not scored:
        raise ValueError(
            "no date in this run produced a fusion score; every row is "
            "belum_dapat_dinilai, so weight sensitivity is undefined"
        )
    baseline_scores = np.array([baseline_results[i].score for i in scored], dtype=float)

    # A term that never varies contributes nothing to the ranking, and its
    # weight then acts only as a global attenuator of the score against fixed
    # thresholds. Spearman would report a flawless 1.0000 for that weight, which
    # reads as "robust" and actually means "inert". Detecting it here is the
    # difference between the two readings.
    degenerate = _constant_terms([baseline_results[i] for i in scored])

    def summarise(
        name: str, delta: float, results: list[fusion_module.FusionResult], value: float
    ) -> WeightPoint:
        scores = np.array([results[i].score for i in scored], dtype=float)
        levels = [r.level for r in results]
        return WeightPoint(
            weight=name,
            delta=delta,
            value=value,
            skipped=None,
            spearman=_spearman(baseline_scores, scores),
            level_changes=sum(1 for a, b in zip(baseline_levels, levels, strict=True) if a != b),
            n_scored=len(scored),
            siaga=levels.count("siaga"),
            waspada=levels.count("waspada"),
            tenang=levels.count("tenang"),
            belum_dapat_dinilai=levels.count("belum_dapat_dinilai"),
        )

    # The baseline row carries no single "value"; nan keeps the column honest
    # rather than implying one weight is the one being varied.
    baseline_point = summarise("(baseline)", 0.0, baseline_results, float("nan"))

    points: list[WeightPoint] = []
    for name in WEIGHT_NAMES:
        for delta in deltas:
            perturbed = _perturbed(cfg.weights, name, delta)
            if perturbed is None:
                points.append(
                    WeightPoint(
                        weight=name,
                        delta=delta,
                        value=float("nan"),
                        skipped=f"{name} {delta:+.2f} leaves [0, 1]",
                    )
                )
                continue
            variant = cfg.model_copy(update={"weights": perturbed})
            results = [fusion_module.fuse(inp, variant) for inp in inputs]
            point = summarise(name, delta, results, getattr(perturbed, name))
            if name in degenerate:
                point.inert_because = (
                    f"the {name} term is {degenerate[name]:.4f} on every scored day, so this "
                    f"weight cannot change the ranking; Spearman 1.0 here means inert, "
                    f"not robust"
                )
            points.append(point)
    return points, baseline_point


TERM_TO_WEIGHT = {"A": "anomaly", "M": "momentum", "D": "demand", "C": "corroboration"}


def _constant_terms(results: list[fusion_module.FusionResult]) -> dict[str, float]:
    """Weight names whose fusion term takes the same value on every scored day."""
    constant: dict[str, float] = {}
    for term, weight_name in TERM_TO_WEIGHT.items():
        values = {r.components.get(term) or 0.0 for r in results}
        if len(values) == 1:
            constant[weight_name] = float(next(iter(values)))
    return constant


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    """Rank correlation without a SciPy dependency.

    Ties are averaged, which is what `rankdata` does and what Spearman assumes;
    fusion scores tie often because many days score exactly 0.
    """
    if len(a) < 2:
        return float("nan")
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


# ---------------------------------------------------------------------------
# the whole sweep
# ---------------------------------------------------------------------------
@dataclass
class AblationReport:
    run_id: int | None = None
    k_points: list[KCurvePoint] = field(default_factory=list)
    contamination_points: list[ContaminationPoint] = field(default_factory=list)
    weight_points: list[WeightPoint] = field(default_factory=list)
    weight_baseline: WeightPoint | None = None
    accuracy_available: bool = False
    accuracy_blocked_because: str = ""

    def as_params(self) -> dict[str, Any]:
        return {
            "contamination_grid": list(CONTAMINATION_GRID),
            "weight_deltas": list(WEIGHT_DELTAS),
            "accuracy_available": self.accuracy_available,
        }


def run(
    conn: Conn,
    anomaly_run_id: int,
    analysis: AnalysisConfig | None = None,
    fusion: FusionConfig | None = None,
) -> AblationReport:
    cfg = analysis or load_analysis()
    fcfg = fusion or load_fusion()
    report = AblationReport()

    report.k_points = k_curve(conn, cfg)
    report.contamination_points = contamination_sweep(conn, cfg)
    report.weight_points, report.weight_baseline = weight_sensitivity(conn, anomaly_run_id, fcfg)

    n_events = len(fetch_all(conn, "select 1 from public.gt_events limit 1"))
    report.accuracy_available = n_events > 0
    if not report.accuracy_available:
        report.accuracy_blocked_because = (
            "no adjudicated gt_events. Precision, recall and F1 for each parameter "
            "setting cannot be computed until two annotators have labelled the pool "
            "and their disagreements have been resolved. The sweeps above describe "
            "how the output moves, not whether it improves."
        )
    return report
