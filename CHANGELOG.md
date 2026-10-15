# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Modern React + Tailwind CSS frontend interface with real-time progress indicators, interactive statistics visualizations, gene frequency charting, and one-click data previews.
- FastAPI backend service (`streamlit_app.api_server`) exposing annotation endpoints, sample dataset inspection, and progress tracking.
- Automated frontend linting and build validation step (`oxlint` + `vite build`) in GitHub Actions CI workflow (`python-tests.yml`).
- Multi-stage Docker build producing an optimized production container image with embedded frontend assets and non-root user execution (`appuser:appgroup`).

## [0.1.0-rc2] - 2026-10-02

### Added
- Assembly-aware chromosome normalization architecture supporting standard assemblies (GRCh38, GRCh37, GRCm39, etc.) and custom coordinate registries.
- Strict parity verification harness between Bedtools and Polars-Bio backends across overlap, closest, and strand-aware modes.
- End-to-end container health smoke checks and deterministic benchmark harness in CI.
- Comprehensive documentation covering deployment, architecture, engine contracts, and reproducibility.

### Changed
- Streamlit application unified backend selection allowing dynamic engine switching with guaranteed schema parity.
- License formalized as BSD-3-Clause across codebase, packaging, and metadata.

## [0.1.0-rc1] - 2026-09-28

### Added
- Initial release candidate for AnnotateR on SciLifeLab Serve.
- Core genomic coordinate annotation pipeline with interchangeable Bedtools and Polars-Bio execution engines.
- Basic Streamlit UI for coordinate upload (BED, VCF), annotation files (BED, GFF, GTF), and tabular exports.
