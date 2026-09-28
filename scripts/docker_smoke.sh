#!/bin/sh
# In-container smoke test for the AnnotateR production image (Task 8).
#
# Verifies, in order:
#   1. bedtools is on PATH at the expected version;
#   2. core imports succeed (app package + both engines + canonical adapter);
#   3. a canonical smoke annotation completes with BOTH engines on the
#      bundled example data, and the two canonical results are strictly
#      equal (the same strict comparator the parity suite uses);
#   4. Streamlit starts from the Serve entry point (app.py), passes the
#      health endpoint, and the UI endpoint responds.
#
# Exits non-zero on the first failure.  Used by CI (docker job) and by
# local deployment verification (see docs/deployment.md).
set -eu

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

# --- 1. bedtools ----------------------------------------------------------
command -v bedtools >/dev/null 2>&1 || fail "bedtools not found on PATH"
# `bedtools --version` prints e.g. "bedtools v2.31.1"; extract the number.
BEDTOOLS_VERSION_RAW="$(bedtools --version 2>/dev/null | head -n1)"
BEDTOOLS_VERSION="$(printf '%s\n' "$BEDTOOLS_VERSION_RAW" | sed -n 's/.*v\([0-9][0-9.]*\).*/\1/p')"
echo "bedtools: ${BEDTOOLS_VERSION_RAW}"
[ -n "$BEDTOOLS_VERSION" ] || fail "could not parse bedtools version from: ${BEDTOOLS_VERSION_RAW}"
case "$BEDTOOLS_VERSION" in
    2.31.*) echo "bedtools version OK (2.31.x)" ;;
    *) fail "unexpected bedtools version: ${BEDTOOLS_VERSION}" ;;
esac

# --- 2+3. imports, engines, canonical smoke annotation --------------------
python - <<'EOF'
import sys

import pandas as pd

from streamlit_app.core.annotator import BedtoolsEngine, PolarsBioEngine
from streamlit_app.core.comparison import assert_canonical_equal
from streamlit_app.core.normalization import parse_and_normalize
from streamlit_app.core.schema import canonicalize_annotation_result

coords = parse_and_normalize("/app/data/examples/example_coordinates.bed", fmt="bed")
annot = parse_and_normalize("/app/data/examples/example_annotations.gff3", fmt="gff")
assert len(coords) > 0 and len(annot) > 0, "example inputs must be non-empty"

results = {}
for key, cls in (("bedtools", BedtoolsEngine), ("polars-bio", PolarsBioEngine)):
    engine = cls(use_strand=False, mode="overlap")
    raw = engine.intersect(coords, annot, how="inner")
    results[key] = canonicalize_annotation_result(raw, coords, annot)
    print(f"{key}: {len(results[key])} canonical rows")

# Strict parity gate: exact columns, row count, row order, cells, dtypes.
assert_canonical_equal(results["bedtools"], results["polars-bio"],
                       label="docker-smoke")
print("canonical smoke annotation: parity verified")

# closest smoke: the shared canonical path must also work in the container
for key, cls in (("bedtools", BedtoolsEngine), ("polars-bio", PolarsBioEngine)):
    engine = cls(use_strand=False, mode="closest")
    raw = engine.intersect(coords, annot, how="inner")
    results[key + "_closest"] = canonicalize_annotation_result(
        raw, coords, annot, extra_columns=("distance",))
assert_canonical_equal(results["bedtools_closest"], results["polars-bio_closest"],
                       label="docker-smoke-closest")
print("closest smoke annotation: parity verified")
EOF

# --- 4. Streamlit from the Serve entry point ------------------------------
echo "starting streamlit (entry point: app.py) ..."
python -m streamlit run app.py --server.port=8501 --server.address=0.0.0.0 \
    > /tmp/streamlit_smoke.log 2>&1 &
STREAMLIT_PID=$!

ok=""
# 180s budget: native container starts in ~10s; under QEMU emulation
# (arm64 hosts) the first import chain can take several minutes.
for _ in $(seq 1 180); do
    if curl -fsS http://localhost:8501/_stcore/health >/dev/null 2>&1; then
        ok=1
        break
    fi
    if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
        break
    fi
    sleep 1
done
[ -n "$ok" ] || { cat /tmp/streamlit_smoke.log >&2; fail "streamlit health check failed"; }
echo "health endpoint: OK"

HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8501/)"
[ "$HTTP_CODE" = "200" ] || fail "UI endpoint returned HTTP ${HTTP_CODE}"
echo "UI endpoint: HTTP ${HTTP_CODE} OK"

kill "$STREAMLIT_PID" 2>/dev/null || true
wait "$STREAMLIT_PID" 2>/dev/null || true

echo "SMOKE PASS"