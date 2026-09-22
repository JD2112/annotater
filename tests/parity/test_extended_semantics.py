"""
Extended semantics (PLAN Task 3) — strand handling.

Only the part of the strand contract that is already normative is tested
here:

- SPEC 8.3: when ``use_strand=False`` (the only currently wired value),
  strand MUST NOT affect matching; opposite-strand intervals overlap
  exactly like strand-less intervals. Strand round-trips as ordinary
  metadata in the canonical result.

Documented gaps (NOT tested, to avoid inventing behavior — SPEC 8.2-8.5,
engine-contract section 5, PLAN Task 6):

- ``use_strand=True`` semantics: the engines do not yet implement it
  (BedtoolsEngine takes no strand argument at all; PolarsBioEngine
  ignores the flag). No fixture asserts True behavior.
- ``min_overlap``: accepted by the shared ``AnnotationEngine`` constructor
  and wired to bedtools ``-f`` by BedtoolsEngine, but the mapping between
  the SPEC notion of minimum overlap and bedtools ``-f``/``-F``/``-r``/``-e``
  is not yet fixed, and PolarsBioEngine ignores the parameter; parity is
  therefore not asserted (engine-contract section 9).
- ``contains`` / ``within`` / ``closest`` modes are not normative for
  this task.
"""

from __future__ import annotations

import pytest

from .cases import STRAND_CASES
from .comparator import check_expected
from .conftest import case_engine_params


@pytest.mark.parametrize("case_engine", case_engine_params(STRAND_CASES))
def test_strand_neutral_matching_when_use_strand_false(case_engine):
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