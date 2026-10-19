"""Sample coordinate consistency (issue #54).

A bundled sample is parsed by ``load_sample`` under each file's
format-authoritative source system -- BED is 0-based half-open, GFF3 and
VCF are 1-based -- regardless of the coordinate declaration the UI happens
to be displaying. Before the fix the load response carried no coordinate
information, so the React selectors kept showing the user's previous
selection, which no longer described the stored data; changing a selector
then demanded a pointless re-upload of the sample.

These tests pin the scientific half of the fix at the HTTP/core boundary:

* every bundled sample declares and reports the system its query and
  annotation were actually normalized under;
* the loaded tables carry exactly one normalization (no double shift);
* a one-base boundary fixture whose match count changes when the
  annotation is interpreted under the wrong system.

The presentation half (selectors reflect the reported convention, and the
N2 invalidation/re-upload contract is preserved) lives in
``frontend/src/app.behavior.test.jsx``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from streamlit_app import api_server
from streamlit_app.api_server import SAMPLE_DATASETS, app
from streamlit_app.api_sessions import SESSION_COOKIE_NAME, SessionStore
from streamlit_app.core import FormatDetector, GFFParser, parse_and_normalize
from streamlit_app.core.engine_registry import engine_available
from streamlit_app.core.normalization import coordinate_system_for, normalize_intervals
from streamlit_app.utils import get_example_data_path
from tests.revision_client import RevisionClient

#: The authoritative source system each bundled sample must be parsed under,
#: keyed by (sample_id, role). Mirrors the format specification, not the file
#: name alone: BED (.bed) is 0-based, GFF3 (.gff3) and VCF (.vcf) are 1-based.
EXPECTED_SYSTEMS = {
    ("gene_overlap", "query"): "0-based",
    ("gene_overlap", "annot"): "1-based",
    ("closest_variants", "query"): "1-based",
    ("closest_variants", "annot"): "1-based",
    ("stranded_features", "query"): "0-based",
    ("stranded_features", "annot"): "1-based",
}


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(api_server, "store", SessionStore())


@pytest.fixture()
def client():
    return RevisionClient(app)


def _session(tab):
    return api_server.store.get(tab.cookies.get(SESSION_COOKIE_NAME))


def _load(client, sample_id):
    response = client.post("/api/load-sample", data={"sample_id": sample_id})
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 1 / 3: every bundled sample loads and reports its authoritative convention
# ---------------------------------------------------------------------------


def test_sample_catalog_declares_a_system_per_side():
    catalog = TestClient(app).get("/api/sample-datasets").json()
    by_id = {s["id"]: s for s in catalog}
    assert set(by_id) == {sample_id for sample_id, _ in EXPECTED_SYSTEMS}
    for (sample_id, role), system in EXPECTED_SYSTEMS.items():
        key = f"{role}_coord_system"
        assert by_id[sample_id][key] == system


@pytest.mark.parametrize("sample_id", sorted({s for s, _ in EXPECTED_SYSTEMS}))
def test_load_sample_reports_the_applied_system_per_side(client, sample_id):
    body = _load(client, sample_id)
    assert body["query"]["coordinate_system"] == EXPECTED_SYSTEMS[(sample_id, "query")]
    assert body["annot"]["coordinate_system"] == EXPECTED_SYSTEMS[(sample_id, "annot")]


def test_declared_systems_match_the_normalization_precedence(client):
    """The declaration is the applied value, derived by the same rule.

    For an authoritative extension the format specification wins, so the
    catalog's explicit declaration and the precedence resolver must agree;
    the loader reports exactly that value.
    """
    for sample_id, sample in SAMPLE_DATASETS.items():
        for role in ("query", "annot"):
            path = get_example_data_path(sample[f"{role}_file"])
            fmt = FormatDetector.detect(str(path))
            applied = coordinate_system_for(
                fmt, sample[f"{role}_coord_system"], extension=path.suffix
            )
            assert sample[f"{role}_coord_system"] == applied
        body = _load(client, sample_id)
        assert body["query"]["coordinate_system"] == sample["query_coord_system"]
        assert body["annot"]["coordinate_system"] == sample["annot_coord_system"]


# ---------------------------------------------------------------------------
# 3 / 7: the stored tables carry the right canonical coordinates, once
# ---------------------------------------------------------------------------


def test_bed_query_is_not_shifted(client):
    """BED is already 0-based half-open: the first interval passes through."""
    _load(client, "gene_overlap")
    q_df = _session(client).data["query"]["df"]
    assert list(q_df["start"])[:2] == [100000, 200000]
    assert list(q_df["end"])[:2] == [100500, 200300]


def test_vcf_query_is_shifted_exactly_once(client):
    """VCF POS is 1-based: first POS 1200 becomes canonical start 1199."""
    _load(client, "closest_variants")
    q_df = _session(client).data["query"]["df"]
    assert list(q_df["start"]) == [1199, 1550, 3750, 99]
    # Single-position variants occupy one base: start + 1 == end.
    assert list(q_df["end"] - q_df["start"]) == [1, 1, 1, 1]


def test_gff3_annotation_is_shifted_exactly_once(client):
    """GFF3 is 1-based inclusive: gene 50000-150000 -> canonical 49999-150000.

    A second shift (double normalization) would give 49998 and is what this
    assertion is built to catch.
    """
    _load(client, "gene_overlap")
    a_df = _session(client).data["annot"]["df"]
    first = a_df.iloc[0]
    assert (first["chr"], first["start"], first["end"]) == ("chr1", 49999, 150000)
    # Row count is preserved by normalization (SPEC 5.6): no rows added/merged.
    assert len(a_df) == 8


# ---------------------------------------------------------------------------
# 6: execution after a sample load uses the loaded, normalized datasets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sample_id,mode",
    [("gene_overlap", "overlap"), ("stranded_features", "overlap"), ("closest_variants", "closest")],
)
def test_execution_after_sample_load_succeeds(client, sample_id, mode):
    if not engine_available("bedtools"):
        pytest.skip("bedtools binary unavailable")
    _load(client, sample_id)
    response = client.post("/api/execute", json={"engine": "bedtools", "mode": mode})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stats"]["result_count"] >= 1
    assert body["stats"]["matched_query_count"] >= 1


# ---------------------------------------------------------------------------
# 8: a boundary fixture whose match count changes under a wrong interpretation
# ---------------------------------------------------------------------------

# Query BED chr1 [100, 105) covers 0-based bases 100..104.
# Annotation GFF3 gene 105..106 is 1-based inclusive, i.e. the single base at
# 1-based position 105, canonical [104, 106). The two touch at 0-based 104 and
# overlap by one base -- but only under the correct (1-based) reading. Read as
# 0-based, the gene becomes [105, 106), which starts exactly where the query
# ends, and the intervals no longer overlap.
_BOUNDARY_QUERY = "chr1\t100\t105\n"
_BOUNDARY_ANNOT = "chr1\tsrc\tgene\t105\t106\t.\t+\t.\tID=g1\n"


def _overlap_count(query_df, annot_df):
    count = 0
    for _, q in query_df.iterrows():
        for _, a in annot_df.iterrows():
            if q["chr"] == a["chr"] and q["start"] < a["end"] and a["start"] < q["end"]:
                count += 1
    return count


def test_boundary_fixture_wrong_interpretation_changes_match_count(tmp_path):
    query_path = tmp_path / "boundary_query.bed"
    annot_path = tmp_path / "boundary_annot.gff3"
    query_path.write_text(_BOUNDARY_QUERY, encoding="utf-8")
    annot_path.write_text(_BOUNDARY_ANNOT, encoding="utf-8")

    # The authoritative parse: BED 0-based, GFF3 1-based.
    query_df = parse_and_normalize(str(query_path))
    annot_df = parse_and_normalize(str(annot_path))
    assert coordinate_system_for("bed", None, extension=".bed") == "0-based"
    assert coordinate_system_for("gff", None, extension=".gff3") == "1-based"
    assert _overlap_count(query_df, annot_df) == 1

    # The same bytes read with the annotation wrongly declared 0-based: the
    # one-base boundary is lost and the match disappears.
    wrong_annot = normalize_intervals(
        GFFParser.parse(str(annot_path)), coordinate_system="0-based"
    )
    assert _overlap_count(query_df, wrong_annot) == 0
