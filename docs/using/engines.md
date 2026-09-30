# Choosing an annotation engine (Bedtools vs Polars-Bio)

AnnotateR executes every operation on one of two **annotation
engines**:

| Engine | Implementation | Requirement |
|---|---|---|
| **Bedtools (default)** | the established `bedtools` command-line tool, invoked as a subprocess | a `bedtools` binary available on the deployment's system PATH |
| **Polars-Bio** | the pure-dataframe Polars-Bio library | installed in the Python environment (it is a core dependency) |

## The core promise

For every supported operation and option, AnnotateR defines the
semantics and **both engines are required to return the same
canonical result**: identical rows, identical column values. The
engine is an *implementation choice*, not a scientific one — this is
the **backend parity** requirement of the
[scientific contract](../technical/scientific-contract.md), and it is
enforced by the test suite
([Backend parity and benchmark](../benchmark.md)).

## Why two engines at all

- **Bedtools** is the established command-line interval-processing
  backend used by AnnotateR for the backend operations where
  applicable. AnnotateR itself defines the canonical semantics and
  output contract: `min_overlap`, strand, and the `contains`/`within`
  predicates are shared AnnotateR post-processing applied on top of
  backend pair generation, and `closest` uses the shared canonical
  closest implementation rather than exposing a backend-native
  distance. An equivalent-looking `bedtools` shell pipeline is
  therefore not a specification of AnnotateR output.
- **Polars-Bio** runs in-process, with no external binary. In the
  [AnnotateR benchmark](../benchmark.md), Polars-Bio was faster for
  pair-producing operations such as `overlap`, `contains`, and `within`
  on the measured workloads. `closest` uses the shared canonical
  AnnotateR path, so its runtime is similar across backends.

## How to choose

The practical default: **leave it on Bedtools** (it is the app
default). Pick **Polars-Bio** when:

- your environment has no `bedtools` on PATH (the Bedtools option will
  be unavailable at run time and the run would fail with an explicit
  message);
- you are running a pair-producing operation (`overlap`, `contains`,
  or `within`) and want the in-process engine that the
  [AnnotateR benchmark](../benchmark.md) measured as faster for those
  operations on the tested workloads (`closest` runs the shared
  canonical implementation on both backends, so it has similar
  runtime there);
- you simply want to cross-check a result — re-running the same
  configuration on the other engine and diffing the two downloads is a
  legitimate way to sanity-check your inputs.

## Availability is shown, not hidden

- If the selected engine is not available in this deployment, a warning
  in the sidebar names the backend and what to do — the **run then
  fails with an explicit error**, never a silent fallback to the other
  engine.
- **Bedtools** requires a `bedtools` binary on the deployment's system
  PATH. If it is missing (for example in some container images), the
  Polars-Bio engine covers the same operations with identical results.
- The exact failure message names the engine, so you can report it
directly — see [Troubleshooting → engine unavailable](../troubleshooting.md#engine-unavailable).

## Engine and other options are independent

The engine does not change which formats, operations, or options are
available, and it never changes the result columns. The only place an
engine choice could change anything is *performance*, never *content*.
(One caveat for the curious: Bedtools runs through an external process
that uses a temporary directory; a very restrictive deployment may need
its `TMPDIR` reachable — see [Deployment](../deployment.md).)

## Where to go next

- [Configuring the analysis](configuring.md) — the full sidebar tour.
- [FAQ → Can I switch engines mid-analysis?](../faq.md)
- [Technical Reference → Backend parity and benchmark](../benchmark.md) —
  how parity is verified and the performance numbers.