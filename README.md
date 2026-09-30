# AnnotateR

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](https://opensource.org/license/bsd-3-clause)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/pyrevo/annotater/actions/workflows/python-tests.yml/badge.svg)](https://github.com/pyrevo/annotater/actions/workflows/python-tests.yml)

AnnotateR is a web application for reproducible annotation of genomic
intervals. It maps a set of input coordinates (BED, GFF3, GTF, VCF, or
custom CSV/TSV tables) against a gene or feature annotation set and
produces a canonical result table that can be exported as CSV, TSV,
Excel, or (for VCF queries) annotated VCF. Interval arithmetic runs on
Bedtools or Polars-Bio; the two are interchangeable execution backends
under AnnotateR's canonical semantics.

## Overview

AnnotateR takes two files: a query file of genomic coordinates and an
annotation file of genomic features. For each query it reports the
annotation features that satisfy the selected interval operation
(overlap, minimum overlap, contains, within, or closest), with optional
explicit strand-aware matching. Results are computed and exported in a
single canonical coordinate model (0-based half-open intervals), so
output is independent of the source format's coordinate convention.

The execution backend is a runtime choice, not a scientific one: for the
supported operations, Bedtools and Polars-Bio produce equivalent
canonical results for the same input and options, and this parity is
enforced by the test suite rather than assumed.

## Features

- Five input formats: BED, GFF3, GTF, VCF (query-only in v0.1.0), and
  custom CSV/TSV tables with explicit column mapping.
- Five interval operations: overlap, minimum query-overlap fraction,
  contains, within, closest; optional same-strand filtering.
- Chromosome identifier normalization: UCSC (`chr1`) and Ensembl (`1`)
  styles are converted automatically; NCBI accession styles are
  recognized but are not a conversion target.
- A single canonical coordinate model: 1-based formats (GFF3, GTF, VCF)
  are converted at parse time; every operation and export uses
  0-based half-open intervals.
- Interchangeable backends: Bedtools and Polars-Bio produce equivalent
  canonical results on the supported operations (parity is test-enforced).
- CSV, TSV, and Excel export of results; annotated VCF export for VCF
  queries.
- Streamlit web application, containerized with Docker for local use
  and deployment.

## Supported operations

All operations are supported by both backends; the backend is an
execution choice and does not change the semantics:

| Operation | Canonical semantics |
|---|---|
| Overlap | positive half-open overlap |
| Minimum query overlap (`min_overlap`) | query-relative overlap fraction |
| Contains | query contains annotation |
| Within | query within annotation |
| Closest | canonical gap distance; all tied-nearest annotations returned |

Strand-aware matching is an option on every operation: it filters to
the same explicit strand, and a missing strand is never treated as a
wildcard. The normative definition of each operation is in
[docs/engine-contract.md](docs/engine-contract.md).

## Getting started

Docker (recommended):

```bash
git clone https://github.com/pyrevo/annotater.git
cd annotater
docker-compose up --build
# -> http://localhost:8501
```

Local installation (Python 3.12):

```bash
git clone https://github.com/pyrevo/annotater.git
cd annotater
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app/streamlit_app.py
# -> http://localhost:8501
```

The Bedtools backend additionally requires the `bedtools` system binary;
the Polars-Bio backend has no such requirement. Then upload a query
file and an annotation file, choose an operation and options, run the
annotation, and export the result. Developer install and test setup is
in [QUICKSTART.md](QUICKSTART.md); the user-level quick start is in the
manual ([quick start](docs/getting-started/quick-start.md)).

## Documentation

The user manual is published at <https://pyrevo.github.io/annotater/>
(also in this repository, rooted at [docs/index.md](docs/index.md)).
Notable pages:

- [Quick start](docs/getting-started/quick-start.md)
- [Supported file formats](docs/preparing-your-data/supported-formats.md)
- [Choosing an operation](docs/operations/choosing-an-operation.md)
- [Coordinate systems](docs/preparing-your-data/coordinate-systems.md)
- [Result columns](docs/results/result-columns.md)
- [Limitations](docs/limitations.md)

Technical reference: [SPEC](SPEC.md) (normative contract),
[architecture](docs/architecture.md),
[engine contract](docs/engine-contract.md),
[deployment](docs/deployment.md) (Docker and SciLifeLab Serve).

## Reproducibility and testing

AnnotateR defines a canonical coordinate model and a canonical result
schema; every backend adapter must map its raw output onto that schema,
and the parity harness verifies that both backends return equivalent
canonical results for each supported operation. The full suite (unit,
integration, parity) runs with a single command from the repository
root:

```bash
pytest
```

Continuous integration (
[.github/workflows/python-tests.yml](.github/workflows/python-tests.yml))
runs the full suite on Ubuntu and macOS (Python 3.12), builds the
production image, runs an in-container smoke test, and runs a
deterministic, parity-gated benchmark smoke.

Backend runtime performance is workload-dependent. The benchmark
characterizes both backends under controlled synthetic workloads with
parity verified before any number is accepted:
[docs/benchmark.md](docs/benchmark.md) (methodology, environment,
results, reproduction) and `benchmarks/benchmark_engines.py`
(deterministic script).

## Citation

Citation metadata is maintained in [CITATION.cff](CITATION.cff) (version
and release date are recorded when the release is made).

## License

AnnotateR is licensed under the BSD 3-Clause License — see
[LICENSE](LICENSE).

## Authors and contact

- Jyotirmoy Das, Ph.D. — [jyotirmoy.das@liu.se](mailto:jyotirmoy.das@liu.se)
- Massimiliano Volpe, Ph.D. — [massimiliano.volpe@scilifelab.se](mailto:massimiliano.volpe@scilifelab.se)

Questions, bug reports, and feature requests: [GitHub Issues](https://github.com/pyrevo/annotater/issues).