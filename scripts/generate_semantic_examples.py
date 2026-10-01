#!/usr/bin/env python3
"""Render the factual interval-example blocks in the docs from fixtures.

Source of truth: tests/fixtures/semantic_examples.json (declarative).
The renderer never computes scientific results; it only displays the
expected facts declared in the fixture. Those facts are verified against
the independent oracle by tests/oracle/test_semantic_examples_oracle.py.

    python scripts/generate_semantic_examples.py          regenerate blocks
    python scripts/generate_semantic_examples.py --check  fail if docs are stale

Only text between these markers is ever replaced:

    <!-- BEGIN GENERATED: <example name> -->
    <!-- END GENERATED: <example name> -->
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "semantic_examples.json"
DOCS_DIR = ROOT / "docs"

CELL = 3  # characters per genomic base in the occupancy diagram

BEGIN_RE = re.compile(r"^<!-- BEGIN GENERATED: ([A-Za-z0-9_]+) -->$")
END_RE = re.compile(r"^<!-- END GENERATED: ([A-Za-z0-9_]+) -->$")

# Declared expected facts and their value types, in display order.
FACT_TYPES = {
    "overlap": bool,
    "overlap_length": int,
    "query_length": int,
    "overlap_fraction": float,
    "min_overlap_pass": bool,
    "contains": bool,
    "within": bool,
    "stranded_match": bool,
    "closest_distance": int,
    "closest_ties": list,
}


class FixtureError(ValueError):
    pass


class MarkerError(ValueError):
    pass


# --------------------------------------------------------------------------
# Fixture loading / schema
# --------------------------------------------------------------------------


def _check_interval(where, iv, *, annotation):
    if not isinstance(iv, dict):
        raise FixtureError(f"{where}: interval must be an object")
    allowed = {"chr", "start", "end", "strand"} | ({"id"} if annotation else set())
    required = {"chr", "start", "end"} | ({"id"} if annotation else set())
    missing = required - iv.keys()
    if missing:
        raise FixtureError(f"{where}: missing {sorted(missing)}")
    extra = iv.keys() - allowed
    if extra:
        raise FixtureError(f"{where}: unexpected keys {sorted(extra)}")
    for key in ("start", "end"):
        if type(iv[key]) is not int:
            raise FixtureError(f"{where}: {key} must be an integer")
    if iv["start"] < 0 or iv["start"] >= iv["end"]:
        raise FixtureError(f"{where}: need 0 <= start < end (half-open)")
    if not isinstance(iv["chr"], str) or not iv["chr"]:
        raise FixtureError(f"{where}: chr must be a non-empty string")
    if "strand" in iv and iv["strand"] not in ("+", "-"):
        raise FixtureError(f"{where}: strand must be '+' or '-' (omit if missing)")


def validate_examples(data):
    """Raise FixtureError unless ``data`` matches the fixture schema."""
    if not isinstance(data, dict) or not isinstance(data.get("examples"), list):
        raise FixtureError("top level must be an object with an 'examples' list")
    seen = set()
    for ex in data["examples"]:
        if not isinstance(ex, dict):
            raise FixtureError("each example must be an object")
        name = ex.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise FixtureError(f"invalid example name {name!r}")
        if name in seen:
            raise FixtureError(f"duplicate example name {name!r}")
        seen.add(name)
        where = f"example {name!r}"
        extra = ex.keys() - {"name", "query", "annotations", "min_overlap",
                             "use_strand", "expected"}
        if extra:
            raise FixtureError(f"{where}: unexpected keys {sorted(extra)}")
        if "query" not in ex:
            raise FixtureError(f"{where}: missing 'query'")
        _check_interval(f"{where} query", ex["query"], annotation=False)
        anns = ex.get("annotations")
        if not isinstance(anns, list) or not anns:
            raise FixtureError(f"{where}: 'annotations' must be a non-empty list")
        ids = []
        for ann in anns:
            _check_interval(f"{where} annotation", ann, annotation=True)
            ids.append(ann["id"])
        if len(set(ids)) != len(ids):
            raise FixtureError(f"{where}: duplicate annotation ids")
        if "min_overlap" in ex:
            v = ex["min_overlap"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not 0 <= v <= 1:
                raise FixtureError(f"{where}: min_overlap must be in [0, 1]")
        if "use_strand" in ex and type(ex["use_strand"]) is not bool:
            raise FixtureError(f"{where}: use_strand must be a boolean")
        exp = ex.get("expected")
        if not isinstance(exp, dict) or not exp:
            raise FixtureError(f"{where}: 'expected' must be a non-empty object")
        for key, value in exp.items():
            if key not in FACT_TYPES:
                raise FixtureError(f"{where}: unknown expected fact {key!r}")
            want = FACT_TYPES[key]
            if want is float:
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            else:
                ok = type(value) is want
            if not ok:
                raise FixtureError(f"{where}: {key} must be {want.__name__}")
        if "closest_ties" in exp and not set(exp["closest_ties"]) <= set(ids):
            raise FixtureError(f"{where}: closest_ties names unknown annotations")
        if "min_overlap_pass" in exp and "min_overlap" not in ex:
            raise FixtureError(f"{where}: min_overlap_pass needs min_overlap")
        if "stranded_match" in exp and not ex.get("use_strand"):
            raise FixtureError(f"{where}: stranded_match needs use_strand")
    return data


def load_examples(path=FIXTURE):
    """Return ``{name: example}`` (fixture order) after schema validation."""
    data = validate_examples(json.loads(Path(path).read_text()))
    return {ex["name"]: ex for ex in data["examples"]}


# --------------------------------------------------------------------------
# Rendering (display of declared values only)
# --------------------------------------------------------------------------


def _yn(value):
    return "yes" if value else "no"


def _strand_text(iv):
    return iv.get("strand", "missing")


def _interval_text(iv, with_strand):
    text = f"[{iv['start']}, {iv['end']})"
    return f"{text}  strand {_strand_text(iv)}" if with_strand else text


def render_block(example):
    """Deterministic text for one example (without the HTML markers)."""
    query = example["query"]
    rows = [("query", query)] + [(a["id"], a) for a in example["annotations"]]
    with_strand = "use_strand" in example or any("strand" in iv for _, iv in rows)
    lo = min(iv["start"] for _, iv in rows)
    hi = max(iv["end"] for _, iv in rows)
    label_w = max(len("bases"), *(len(label) for label, _ in rows)) + 2

    lines = [f"coordinates are 0-based half-open; chromosome {query['chr']}", ""]
    lines.append("bases".ljust(label_w)
                 + "".join(f"{b:>{CELL}}" for b in range(lo, hi)))
    for label, iv in rows:
        cells = "".join(
            f"{'#':>{CELL}}" if iv["start"] <= b < iv["end"] else f"{'.':>{CELL}}"
            for b in range(lo, hi))
        lines.append(f"{label:<{label_w}}{cells}  {_interval_text(iv, with_strand)}")
    lines.append("")
    for label, iv in rows:
        n = iv["end"] - iv["start"]
        span = (f"base {iv['start']}" if n == 1
                else f"bases {iv['start']}–{iv['end'] - 1}")
        lines.append(
            f"{label:<{label_w}}{span} "
            f"({n} {'base' if n == 1 else 'bases'}); "
            f"boundary coordinates {iv['start']} and {iv['end']}")
    lines.append("")

    exp = example["expected"]
    if "min_overlap" in example:
        lines.append(f"min_overlap threshold: {example['min_overlap']:g}")
    if "use_strand" in example:
        lines.append(f"strand matching: {'on' if example['use_strand'] else 'off'}")
    labels = {
        "overlap": ("overlap", _yn),
        "overlap_length": ("overlap length", str),
        "query_length": ("query length", str),
        "overlap_fraction": ("overlap fraction (query-relative)",
                             lambda v: f"{v:g}"),
        "min_overlap_pass": ("passes min_overlap", _yn),
        "contains": ("query contains annotation", _yn),
        "within": ("query within annotation", _yn),
        "stranded_match": ("stranded match", _yn),
        "closest_distance": ("closest distance", str),
    }
    for key in FACT_TYPES:
        if key not in exp:
            continue
        if key == "closest_ties":
            ties = exp[key]
            lines.append(f"closest ties retained: {len(ties)} "
                         f"(annotation order: {', '.join(ties)})")
        else:
            label, fmt = labels[key]
            lines.append(f"{label}: {fmt(exp[key])}")
    return "```text\n" + "\n".join(lines) + "\n```"


# --------------------------------------------------------------------------
# Marker replacement
# --------------------------------------------------------------------------


def replace_blocks(text, rendered, source="<text>"):
    """Replace only the content between markers; return (new_text, names).

    Everything outside the BEGIN/END marker lines is preserved byte for
    byte. Raises MarkerError for unknown names or malformed markers.
    """
    out = []
    names = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m_end = END_RE.match(line)
        if m_end:
            raise MarkerError(f"{source}:{i + 1}: END without BEGIN")
        m = BEGIN_RE.match(line)
        if not m:
            out.append(line)
            i += 1
            continue
        name = m.group(1)
        if name not in rendered:
            raise MarkerError(f"{source}:{i + 1}: unknown example {name!r}")
        if name in names:
            raise MarkerError(f"{source}:{i + 1}: duplicate block {name!r}")
        j = i + 1
        while j < len(lines) and not END_RE.match(lines[j]):
            if BEGIN_RE.match(lines[j]):
                raise MarkerError(f"{source}:{j + 1}: nested BEGIN")
            j += 1
        if j == len(lines):
            raise MarkerError(f"{source}:{i + 1}: BEGIN {name!r} without END")
        if END_RE.match(lines[j]).group(1) != name:
            raise MarkerError(f"{source}:{j + 1}: END does not match BEGIN {name!r}")
        out.append(line)
        out.extend(rendered[name].split("\n"))
        out.append(lines[j])
        names.append(name)
        i = j + 1
    return "\n".join(out), names


def markdown_files(docs_dir=DOCS_DIR):
    return sorted(Path(docs_dir).rglob("*.md"))


def run(*, check=False, fixture=FIXTURE, docs_dir=DOCS_DIR, out=sys.stdout):
    """Process every docs page; return the process exit status."""
    examples = load_examples(fixture)
    rendered = {name: render_block(ex) for name, ex in examples.items()}
    stale = []
    for path in markdown_files(docs_dir):
        old = path.read_text()
        if "GENERATED:" not in old:
            continue
        new, _ = replace_blocks(old, rendered, source=str(path))
        if new != old:
            stale.append(path)
            if not check:
                path.write_text(new)
    for path in stale:
        verb = "stale" if check else "updated"
        print(f"{verb}: {path}", file=out)
    if check and stale:
        print("Generated example blocks are out of date; run "
              "`python scripts/generate_semantic_examples.py`.", file=out)
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="exit nonzero if docs differ; write nothing")
    args = parser.parse_args(argv)
    try:
        return run(check=args.check)
    except (FixtureError, MarkerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
