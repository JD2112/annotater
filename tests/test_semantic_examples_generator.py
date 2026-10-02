"""Schema, determinism and marker-safety tests for the docs example generator."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "generate_semantic_examples.py"

_spec = importlib.util.spec_from_file_location("generate_semantic_examples", SCRIPT)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

EXAMPLES = gen.load_examples()


def _rendered():
    return {n: gen.render_block(e) for n, e in EXAMPLES.items()}


def _markers(name, body=""):
    return (f"<!-- BEGIN GENERATED: {name} -->\n{body}"
            f"<!-- END GENERATED: {name} -->")


# ---- schema ---------------------------------------------------------------

def test_committed_fixture_is_valid():
    assert "touching_intervals" in EXAMPLES


def _mutated(mutate):
    data = json.loads(gen.FIXTURE.read_text())
    mutate(data["examples"][0])
    return data


@pytest.mark.parametrize("mutate", [
    lambda e: e.pop("query"),
    lambda e: e["query"].update(start=5, end=5),
    lambda e: e["query"].update(strand="."),
    lambda e: e["expected"].update(bogus=True),
    lambda e: e["expected"].update(overlap="yes"),
    lambda e: e.update(extra=1),
    lambda e: e.update(annotations=[]),
    lambda e: e.update(min_overlap=1.5),
    lambda e: e["expected"].update(stranded_match=True),
    lambda e: e.update(name="bad name"),
], ids=range(10))
def test_schema_rejects_bad_fixture(mutate):
    with pytest.raises(gen.FixtureError):
        gen.validate_examples(_mutated(mutate))


def test_schema_rejects_duplicate_names():
    data = json.loads(gen.FIXTURE.read_text())
    data["examples"].append(copy.deepcopy(data["examples"][0]))
    with pytest.raises(gen.FixtureError):
        gen.validate_examples(data)


# ---- rendering ------------------------------------------------------------

def test_render_is_deterministic():
    assert _rendered() == _rendered()


def test_min_overlap_block_shows_exact_values():
    text = gen.render_block(EXAMPLES["min_overlap_on_threshold"])
    for line in ("query length: 10", "overlap length: 5",
                 "overlap fraction (query-relative): 0.5"):
        assert line in text


# ---- marker replacement ---------------------------------------------------

def test_replace_touches_only_marked_content():
    before = "# Title\n\nprose before\n\n"
    after = "\nprose after <!-- not a marker -->\n- list\n"
    text = before + _markers("touching_intervals", "stale\n") + after
    new, names = gen.replace_blocks(text, _rendered())
    assert names == ["touching_intervals"]
    assert new.startswith(before + "<!-- BEGIN GENERATED: touching_intervals -->\n")
    assert new.endswith("<!-- END GENERATED: touching_intervals -->" + after)
    assert "stale" not in new
    assert gen.replace_blocks(new, _rendered())[0] == new  # idempotent


def test_text_without_markers_is_unchanged():
    text = "no markers here\n\n```text\nbases\n```\n"
    assert gen.replace_blocks(text, _rendered()) == (text, [])


@pytest.mark.parametrize("text", [
    "<!-- BEGIN GENERATED: nope -->\n<!-- END GENERATED: nope -->",
    "<!-- BEGIN GENERATED: touching_intervals -->\nx",
    "<!-- END GENERATED: touching_intervals -->",
    "<!-- BEGIN GENERATED: touching_intervals -->\n"
    "<!-- END GENERATED: one_base_gap -->",
    "<!-- BEGIN GENERATED: touching_intervals -->\n"
    "<!-- BEGIN GENERATED: one_base_gap -->\n<!-- END GENERATED: one_base_gap -->",
    _markers("touching_intervals") + "\n" + _markers("touching_intervals"),
])
def test_malformed_markers_are_rejected(text):
    with pytest.raises(gen.MarkerError):
        gen.replace_blocks(text, _rendered())


# ---- --check / write modes ------------------------------------------------

def _docs(tmp_path, body):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "page.md").write_text(body)
    (docs / "other.md").write_text("untouched prose\n")
    return docs


def test_check_passes_when_clean_and_fails_when_stale(tmp_path):
    docs = _docs(tmp_path, "intro\n" + _markers("one_base_gap") + "\noutro\n")
    assert gen.run(docs_dir=docs, out=io.StringIO()) == 0  # regenerate
    assert gen.run(check=True, docs_dir=docs, out=io.StringIO()) == 0

    page = docs / "page.md"
    page.write_text(page.read_text().replace("closest distance: 1",
                                             "closest distance: 7"))
    stale = page.read_text()
    out = io.StringIO()
    assert gen.run(check=True, docs_dir=docs, out=out) == 1
    assert "page.md" in out.getvalue()
    assert page.read_text() == stale  # --check never writes

    assert gen.run(docs_dir=docs, out=io.StringIO()) == 0
    assert "closest distance: 1" in page.read_text()
    assert (docs / "other.md").read_text() == "untouched prose\n"


def test_committed_docs_are_up_to_date():
    assert gen.run(check=True, out=io.StringIO()) == 0


def test_every_fixture_example_is_used_in_docs():
    used = set()
    for path in gen.markdown_files():
        used |= {m.group(1) for line in path.read_text().splitlines()
                 if (m := gen.BEGIN_RE.match(line))}
    assert used == set(EXAMPLES)
