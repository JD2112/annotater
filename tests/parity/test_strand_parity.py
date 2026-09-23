"""
Strand contract parity (PLAN Task 6B) — SPEC 8.3.

The single normative definition (fixed by Task 6B):

    use_strand=False:
        strand does not participate in match qualification; a pair may
        match on the interval predicate and other active options alone.

    use_strand=True:
        strand_match(Q, A) =
            Q.strand in {"+", "-"} AND A.strand in {"+", "-"}
            AND Q.strand == A.strand
        and a pair qualifies iff
            interval_predicate(Q, A) AND strand_match(Q, A)

Missing/unknown strand (``pd.NA``, ``None``, a source ``"."`` after
normalization, or an absent strand column) is NOT a wildcard and NOT a
strand: no stranded match is possible for such a row, including
unknown-vs-unknown. Strand composes with ``min_overlap`` by logical AND
(no precedence). In left mode, a query whose geometrical overlaps all
fail the strand predicate is unmatched exactly once.

Each case in ``STRAND_CASES`` carries its expected rows derived from
that definition (never from backend output) and is checked against
BOTH engines independently through the canonical adapter. The direct
engine-vs-engine layer lives in ``test_differential_parity.py``
(strand entries in ``DIFFERENTIAL_CASES``).
"""

from __future__ import annotations

import pandas as pd
import pytest

from streamlit_app.core import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.normalization import parse_and_normalize

from .cases import STRAND_CASES
from .comparator import check_expected, run_and_canonicalize
from .conftest import case_engine_params
from .fixtures import CHR


@pytest.mark.parametrize("case_engine", case_engine_params(STRAND_CASES))
def test_strand_contract(case_engine):
    """Per-engine contract layer: explicit expected rows, both engines."""
    case, engine_cls = case_engine
    check_expected(
        engine_cls,
        case.coord_df,
        case.annot_df,
        case.pairs,
        how=case.how,
        label=case.name,
        **case.engine_kwargs,
    )


def test_strand_dot_source_value_not_wildcard(tmp_path):
    """
    Fixture 7: a source strand of ``"."`` is normalized to canonical
    missing and then does NOT match as ``"+"``, ``"-"``, or a wildcard
    under stranded matching (both engines).
    """
    query = tmp_path / "query.bed"
    query.write_text(f"{CHR}\t10\t20\tq1\t0\t+\n")
    annot = tmp_path / "annot.bed"
    annot.write_text(f"{CHR}\t15\t25\ta1\t0\t.\n")

    q = parse_and_normalize(str(query))
    a = parse_and_normalize(str(annot))

    # Canonical layer: "." (annotation) is canonical missing, not a
    # fourth state; "+" (query) stays explicit.
    assert q["strand"].iloc[0] == "+"
    assert pd.isna(a["strand"].iloc[0])

    for engine_cls in (BedtoolsEngine, PolarsBioEngine):
        # Stranded: "." must not behave as "+", "-", or a wildcard.
        stranded = run_and_canonicalize(
            engine_cls, q, a, how="left", use_strand=True
        )
        assert len(stranded) == 1
        assert not stranded["has_overlap"].iloc[0]

        # Unstranded: matching is by coordinates alone.
        unstranded = run_and_canonicalize(engine_cls, q, a, how="left")
        assert len(unstranded) == 1
        assert unstranded["has_overlap"].iloc[0]