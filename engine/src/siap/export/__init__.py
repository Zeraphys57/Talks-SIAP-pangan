"""Paper exports: figures and tables written to `paper-exports/`.

Everything in this package is regenerated from the database on demand and
nothing in it is committed — `paper-exports/` is gitignored apart from its
`.gitkeep`. A figure in the repository is a figure that can drift from the run
that produced it.

Every artefact is stamped with the `analysis_runs.id` it came from, so a number
in the paper can be traced back to a run, its git SHA, its seed and its
parameters. That chain is the whole point; a chart with no run id behind it is
decoration.

**Nothing here invents a number.** Where an output depends on ground-truth
labels that do not exist yet, the export is skipped and the reason is written
into `paper-exports/README.md`. An empty precision column is a fact; a zero is a
claim.
"""

from __future__ import annotations

from .runner import ExportReport
from .runner import run as run_export

__all__ = ["ExportReport", "run_export"]
