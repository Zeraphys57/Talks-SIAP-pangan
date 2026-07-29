"""Cohen's kappa between two independent annotators (§7.3).

    kappa = (p_observed - p_expected) / (1 - p_expected)

Raw agreement is not enough: two annotators who both label "normal" 90% of the
time will agree 80%+ of the time by chance alone. Kappa subtracts that baseline,
which is why it — and not accuracy — is the number reported in the paper.

**κ >= 0.60 is a gate, not a metric.** Below it the operational definition is too
ambiguous for anything built on top to mean much, and the brief is explicit:
revise the definition, re-label, and report both rounds. Nothing downstream
should be computed from labels that failed this.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..db import Conn, fetch_all

log = logging.getLogger(__name__)

LABELS = ("anomali", "normal", "ragu")


@dataclass
class KappaResult:
    annotator_a: str
    annotator_b: str
    n_paired: int
    observed_agreement: float
    expected_agreement: float
    kappa: float
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    disagreements: list[dict[str, Any]] = field(default_factory=list)

    def passes(self, minimum: float) -> bool:
        return self.kappa >= minimum

    @property
    def interpretation(self) -> str:
        """Landis & Koch (1977) bands, stated so the number is readable."""
        k = self.kappa
        if k < 0.0:
            return "worse than chance"
        if k < 0.20:
            return "slight"
        if k < 0.40:
            return "fair"
        if k < 0.60:
            return "moderate"
        if k < 0.80:
            return "substantial"
        return "almost perfect"


def cohens_kappa(pairs: list[tuple[str, str]]) -> KappaResult:
    """Kappa over paired labels. Pure function, so it is testable without a database."""
    n = len(pairs)
    if n == 0:
        raise ValueError("no paired labels: both annotators must label the same candidates")

    confusion = {a: dict.fromkeys(LABELS, 0) for a in LABELS}
    for label_a, label_b in pairs:
        confusion[label_a][label_b] += 1

    agreed = sum(confusion[label][label] for label in LABELS)
    p_observed = agreed / n

    # Expected agreement from the marginals: what two annotators would achieve
    # if they were labelling independently at their observed base rates.
    p_expected = 0.0
    for label in LABELS:
        row = sum(confusion[label].values()) / n
        col = sum(confusion[other][label] for other in LABELS) / n
        p_expected += row * col

    # p_expected == 1 means both annotators used exactly one label for
    # everything: agreement is total but carries no information, and kappa is
    # undefined. Reporting 0 rather than dividing by zero is the honest answer.
    kappa = 0.0 if p_expected >= 1.0 else (p_observed - p_expected) / (1 - p_expected)

    return KappaResult(
        annotator_a="",
        annotator_b="",
        n_paired=n,
        observed_agreement=p_observed,
        expected_agreement=p_expected,
        kappa=kappa,
        confusion=confusion,
    )


def paired_labels(conn: Conn, annotator_a: str, annotator_b: str) -> list[dict[str, Any]]:
    """Candidates both annotators have labelled."""
    return fetch_all(
        conn,
        """
        select la.candidate_id,
               la.label as label_a, lb.label as label_b,
               c.slug as commodity, rg.slug as region, gc.obs_date,
               gc.sampling_stratum
          from public.gt_labels la
          join public.gt_labels lb
            on lb.candidate_id = la.candidate_id and lb.annotator_code = %s
          join public.gt_candidates gc on gc.id = la.candidate_id
          join public.commodities c on c.id = gc.commodity_id
          join public.regions rg on rg.id = gc.region_id
         where la.annotator_code = %s
         order by gc.obs_date
        """,
        (annotator_b, annotator_a),
    )


def compute(conn: Conn, annotator_a: str, annotator_b: str) -> KappaResult:
    """Kappa for a pair of annotators, with their disagreements listed.

    Disagreements are returned because they are the working material for
    adjudication, not a diagnostic afterthought.
    """
    rows = paired_labels(conn, annotator_a, annotator_b)
    if not rows:
        raise ValueError(
            f"no candidates labelled by both {annotator_a!r} and {annotator_b!r}. "
            f"Kappa needs paired judgements on the same items."
        )

    result = cohens_kappa([(str(r["label_a"]), str(r["label_b"])) for r in rows])
    result.annotator_a, result.annotator_b = annotator_a, annotator_b
    result.disagreements = [
        {
            "candidate_id": r["candidate_id"],
            "commodity": r["commodity"],
            "region": r["region"],
            "obs_date": r["obs_date"],
            "stratum": r["sampling_stratum"],
            annotator_a: r["label_a"],
            annotator_b: r["label_b"],
        }
        for r in rows
        if r["label_a"] != r["label_b"]
    ]
    return result


def annotators(conn: Conn) -> list[str]:
    return [
        str(r["annotator_code"])
        for r in fetch_all(
            conn,
            "select distinct annotator_code from public.gt_labels order by annotator_code",
        )
    ]
