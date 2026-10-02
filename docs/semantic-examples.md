# Semantic interval examples (developer guide)

The small interval diagrams in the user manual are generated from
declarative fixtures so they cannot drift from the scientific contract.
This page is for maintainers; it is excluded from the published site.

## Three separate concerns

| Concern | Where it lives | Rule |
|---|---|---|
| Scientific truth | `tests/oracle/test_semantic_examples_oracle.py` against `tests/oracle/reference.py` | The only layer that evaluates expected values. |
| Rendering contract | `scripts/generate_semantic_examples.py` (`KINDS`, `MAX_WIDTH`, labels, legend, grammar) and `tests/test_semantic_examples_rendering.py` | Presentation only. The renderer displays declared values and never computes or infers them. |
| Human prose | The Markdown pages around the blocks | Hand-written. Never generated. |

## Adding or changing an example

1. Add an entry to `tests/fixtures/semantic_examples.json` with a `kind`
   (`overlap`, `one_base_overlap`, `touching`, `closest`, `closest_tie`,
   `contains`, `within`, `min_overlap`, `strand`). The kind fixes which
   facts must be declared and the order they are shown in; a missing
   required fact fails validation.
2. Declare every expected value in the fixture (including per-candidate
   distances for `closest_tie`). The oracle test checks them.
3. Place a pair of marker lines in a docs page: a line
   `<!-- BEGIN GENERATED: <name> -->` followed by a line
   `<!-- END GENERATED: <name> -->`, with the name of the fixture.
   Each name may appear once per page.
4. Run `python scripts/generate_semantic_examples.py`, then
   `python scripts/generate_semantic_examples.py --check`.

Only text between the marker lines is ever replaced. Generated lines must
stay within `MAX_WIDTH` characters; a wider fixture fails instead of
wrapping, so choose a more compact one.

## When manual visual review is still expected

- a new `kind` or a new diagram layout is introduced;
- the renderer's layout rules, labels, legend or `MAX_WIDTH` change;
- the docs theme or CSS changes (`mkdocs.yml`, `docs/assets`).

Routine fixture additions that pass the rendering-contract tests do not
need a full manual review of every page. Preview with `mkdocs serve`
when a review is required.
