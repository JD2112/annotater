# AnnotateR - Genomic Coordinate Annotation Tool

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.64-red.svg)](https://streamlit.io/)
[![Tests](https://github.com/pyrevo/annotater/actions/workflows/python-tests.yml/badge.svg)](https://github.com/pyrevo/annotater/actions/workflows/python-tests.yml)

A web-based tool for annotating genomic coordinates against a feature set,
with automatic chromosome ID standardization and coordinate system
conversion, a Streamlit interface, and two interchangeable execution
backends (Bedtools and Polars-Bio) that produce identical canonical
results.

## Features

✨ **Key Capabilities:**

- 📁 **Multiple Format Support**: BED, GFF3, GTF, VCF, and custom
  CSV/TSV (including tab-separated exports such as BioMart or UCSC Table
  Browser downloads)
- 🧩 **Chromosome ID Standardization**: auto-detect and convert between
  UCSC (`chr1`), Ensembl (`1`), and NCBI styles
- 📐 **Canonical Coordinates**: all results are computed and reported in
  a single canonical model (0-based half-open intervals); 1-based formats
  (GFF3/GTF/VCF) are converted explicitly at parse time
- 🎯 **Annotation Modes**: overlap (with optional minimum overlap
  fraction), contains, within, closest — all with identical semantics on
  both backends
- ⚡ **Interchangeable Execution Backends**: Bedtools (reference, external
  binary) and Polars-Bio (in-process) are a user-selectable execution
  choice. The same input and options produce the **same canonical result
  and exports** on either backend (parity is test-enforced, not assumed)
- 🔍 **SNP Support**: handle both single positions (VCF) and genomic
  intervals
- 🧪 **Strand-aware matching**: optional, explicit same-strand filtering
- 📊 **Interactive UI**: modern Streamlit interface with real-time
  previews and CSV/TSV/Excel export
- 🐳 **Docker Ready**: containerized for local use and SciLifeLab Serve
  deployment

## Operations and backends

All operations are provided by AnnotateR (shared canonical logic) and are
guaranteed equivalent on both backends; the backend is an implementation
detail the user can switch freely:

| Operation | Bedtools | Polars-Bio | Canonical semantics |
|---|---|---|---|
| Overlap | ✓ | ✓ | positive half-open overlap |
| Minimum query overlap (`min_overlap`) | ✓ | ✓ | query-relative fraction |
| Strand-aware matching | ✓ | ✓ | same explicit strand (missing strand is never a wildcard) |
| Contains | ✓ | ✓ | query contains annotation |
| Within | ✓ | ✓ | query within annotation |
| Closest | ✓ | ✓ | canonical gap distance; all tied-nearest annotations returned |

The backend may change *where* the computation runs (bedtools binary vs
in-process Polars-Bio), never *what* it returns. See
[docs/engine-contract.md](docs/engine-contract.md) for the normative
definition of each operation.

## Quick start

### Using Docker (recommended)

```bash
git clone https://github.com/pyrevo/annotater.git
cd annotater
docker-compose up --build
# -> http://localhost:8501
```

### Local installation

```bash
git clone https://github.com/pyrevo/annotater.git
cd annotater

# bedtools system binary — required only for the Bedtools backend
# (the Polars-Bio backend is fully in-process)
brew install bedtools          # macOS
# sudo apt-get install bedtools  # Debian/Ubuntu

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

streamlit run streamlit_app/streamlit_app.py
# -> http://localhost:8501
```

Then follow [QUICKSTART.md](QUICKSTART.md) to upload files, run an
annotation, and download results.

## Usage

1. **Upload files** — a coordinate file (BED/VCF/CSV/TSV) and an
   annotation file (GFF3/GTF/BED/CSV/TSV).
2. **Configure** (all have safe defaults):
   - **Engine**: Bedtools or Polars-Bio (interchangeable backends)
   - **Coordinate system**: auto-detected by default
   - **Chromosome IDs**: auto-converted by default
   - **Mode**: overlap / contains / within / closest
   - **Strand matching**: off by default; when on, both intervals must
     carry an explicit, equal strand
   - **Minimum overlap fraction**: overlap mode only (0 = any positive
     overlap)
   - **Feature type filter**: GFF3/GTF annotations
3. **Run annotation** — view the canonical result table, inspect metrics,
   and download as CSV, TSV, or Excel.

### Example

```text
# Coordinate file (BED, 0-based half-open):
chr1    100000  100500  region1
chr2    200000  200300  region2

# Annotation file (GFF3, 1-based inclusive — converted at parse time):
chr1    RefSeq  gene    50000   150000  .   +   .   gene_id "GENE1"
chr1    RefSeq  exon    99000   101000  .   +   .   gene_id "GENE1"

# Result: region1 annotated with GENE1 (the gene and its exon overlap
# [100000, 100500)); region2 has no overlap in this example.
```

## Coordinate model

| System | Formats | Interval type | Example |
|--------|---------|---------------|---------|
| 0-based | BED | Half-open `[start, end)` | `[100, 200)` = positions 100–199 |
| 1-based | GFF3, GTF, VCF | Closed `[start, end]` | `[101, 200]` = positions 101–200 |

AnnotateR converts at the parser boundary; every downstream operation and
every exported result uses the canonical 0-based half-open model. VCF
variants are expanded to intervals using the standard REF/END rules.

## Testing status

The full test suite (unit, integration, and the Bedtools↔Polars-Bio parity
harness) is documented in
[QUICKSTART.md](QUICKSTART.md#-development-environment-and-tests); the
single documented command is:

```bash
pytest
```

CI runs the full suite on Ubuntu and macOS (Python 3.12), builds the
production image, and runs the in-container smoke test plus a
deterministic, parity-gated benchmark smoke
([.github/workflows/python-tests.yml](.github/workflows/python-tests.yml)).

## Performance

Backend performance is workload-dependent; the benchmark characterizes
both backends under controlled synthetic workloads (sizes, densities,
operations) with parity verified before any number is accepted:

- **[docs/benchmark.md](docs/benchmark.md)** — methodology, environment,
  results, interpretation, and how to reproduce
- `benchmarks/benchmark_engines.py` — the deterministic benchmark script

## Deployment

- **SciLifeLab Serve** (and general container deployment):
  **[docs/deployment.md](docs/deployment.md)** — image build, local
  container test, Serve setup step-by-step, configuration, verification,
  common failure modes.
- **docker-compose** is provided for local container use.

## Architecture

```
annotater/
├── app.py                     # SciLifeLab Serve entry-point shim
├── streamlit_app/
│   ├── streamlit_app.py       # Main Streamlit application
│   ├── core/                   # Parsers, normalization, engines, schema
│   ├── utils/                  # Validation, helpers
│   └── config/                 # Settings
├── benchmarks/                 # Deterministic backend benchmark
├── scripts/                    # In-container smoke test
├── tests/                      # Unit/integration/parity test suites
├── docs/                       # Architecture, engine contract, deployment,
│                               # benchmark, references, implementation notes
├── data/examples/              # Bundled example inputs
├── app/                        # Legacy Shiny app (superseded, not part of the product;
│                               # retained temporarily — see docs/legacy.md)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt / requirements-dev.txt
```

See [docs/architecture.md](docs/architecture.md) for the module layout and
[docs/engine-contract.md](docs/engine-contract.md) for the backend
contract.

## Documentation

| Document | Contents |
|---|---|
| [SPEC.md](SPEC.md) | Normative product/scientific contract |
| [QUICKSTART.md](QUICKSTART.md) | Install, run, configure, test |
| [docs/architecture.md](docs/architecture.md) | Module architecture |
| [docs/engine-contract.md](docs/engine-contract.md) | Engine semantics and backend contract |
| [docs/deployment.md](docs/deployment.md) | Docker and SciLifeLab Serve deployment |
| [docs/benchmark.md](docs/benchmark.md) | Backend benchmark methodology and results |
| [docs/references.md](docs/references.md) | External manuals for version-sensitive decisions |
| [docs/implementation-notes.md](docs/implementation-notes.md) | Per-task implementation record |
| [docs/legacy.md](docs/legacy.md) | Legacy R files: inventory and temporary-retention status |
| [docs/release-plan-0.1.0.md](docs/release-plan-0.1.0.md) | Post-acceptance v0.1.0 release steps |

## Limitations

- **Input formats**: BED, GFF3, GTF, VCF, and custom delimited tables
  (chr/start/end). Other formats (e.g., BAM, BEDPE) are not supported.
- **Coordinates**: canonical results are 0-based half-open. The Bedtools
  backend (via pybedtools) cannot process coordinates ≥ 2³¹
  (2,147,483,647); all natural chromosomes are far below this bound, so
  real genomic data is unaffected (see
  [docs/benchmark.md](docs/benchmark.md)).
- **Runtime**: Python ≥ 3.12, < 3.15 is install-compatible; 3.12 is the
  tested and supported runtime. The production Docker image is
  `linux/amd64` only (Polars-Bio wheel availability; see
  [docs/deployment.md](docs/deployment.md)).
- **Memory**: inputs and canonical results are held in memory; very large
  files (hundreds of MB) require proportionally large RAM. There is no
  streaming/lazy execution yet.
- **Closest mode**: returns all tied-nearest annotations with a canonical
  `distance`; there is no `k > 1` ranked nearest list and no signed
  upstream/downstream nearest mode.
- **UI**: single-user interactive tool; no account system, no saved
  projects, no server-side persistence (uploads are processed in memory).
- **Deployment**: on SciLifeLab Serve the platform caps uploads at
  100 MB per file.

## Development

```bash
# Full test suite (from the repository root)
pytest

# Formatting / lint (as configured in CI)
black streamlit_app/
ruff check streamlit_app/
```

## Citation

Citation metadata is maintained in
[CITATION.cff](CITATION.cff).

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE)

## Authors

- **Jyotirmoy Das, Ph.D.** - Conceptualization & Development
- **Massimiliano Volpe, Ph.D.** - Conceptualization & Development

## Contact

For questions, bug reports, or feature requests:
- Email: [jyotirmoy.das@liu.se](mailto:jyotirmoy.das@liu.se) | [massimiliano.volpe@scilifelab.se](mailto:massimiliano.volpe@scilifelab.se)
- Issues: GitHub Issues

## Acknowledgments

- SciLifeLab for hosting and support
- bedtools team for the fast intersection engine
- Streamlit team for the amazing web framework
- The bioinformatics community for feedback and testing