# Running the annotation

## The run button

The **Run annotation** button (header "2. Run annotation", top of the
main column) starts the run for the **current** configuration: the two
uploaded files, the selected engine, operation, join, input options,
advanced options, and feature filter.

It is disabled until **both** files are uploaded and parsed.

## Configuration changes invalidate stored results

AnnotateR keeps the last result only while the configuration is
unchanged. **Any** change to engine, operation, join, coordinate-system
declaration, chromosome handling, strand, `min_overlap`, feature
filter — or replacing either file — invalidates the stored result
explicitly. After a change, the results section shows:

> "No results yet. Upload both files, configure the operation, and run
> the annotation."

until you press Run annotation again. A stale result table is never
displayed as if it belonged to the current configuration.

## A successful run

Pressing the button executes the interval operation on the selected
engine and replaces the results section with:

- the provenance caption (`engine · operation · join`),
- the four summary metrics,
- the Show filter,
- the result table,
- the download buttons,
- the charts and gene list expander.

The whole pipeline (parse → normalize → operate → canonicalize) runs
in your session; nothing is sent to or stored on a server.

## Failure states

Failures are explicit errors that name what failed:

- **Malformed file** — parsing stops with a message including the
  offending line (e.g. "line 7: expected at least 3 tab-separated
  fields"). No partial parse is used.
- **Invalid interval** — e.g. `start >= end` or a non-integer
  coordinate, with the offending rows listed.
- **Engine unavailable** — the selected engine's backend is missing in
  this deployment. The message names the backend; there is **no silent
  fallback** to the other engine
  ([Choosing an annotation engine](engines.md),
  [Troubleshooting → engine unavailable](../troubleshooting.md#engine-unavailable)).
- **Chromosome-style conflict** — e.g. you chose manual "Keep original"
  but the two files use different chromosome naming styles; the message
  tells you to re-run with auto-convert or a manual target style
  ([Chromosome identifiers](../preparing-your-data/chromosome-identifiers.md)).

An error means the run **could not happen**. A run that happens and
finds nothing is the informational "No qualifying annotations were
found…" state — a valid result, not an error
([Understanding the results page → informational states](../results/results-page.md#informational-states-not-errors)).

## Re-running

You can re-run as many times as you like; each run replaces the
previous result entirely. Changing an option and running again is the
normal workflow — not a mistake and not an expensive operation for the
bundled examples.