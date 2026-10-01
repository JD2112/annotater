#!/usr/bin/env bash
# Generate requirements.txt / requirements-dev.txt from uv.lock.
#
# uv.lock is the single source of truth for the resolved dependency graph;
# the requirements files are generated compatibility exports (plain pip
# users). They are fully pinned (including transitive dependencies) but
# carry no hashes; the Docker build consumes uv.lock directly, with hashes.
#
#   scripts/export_requirements.sh          regenerate both files
#   scripts/export_requirements.sh --check  fail if either file is stale
#                                           or uv.lock is out of sync with
#                                           pyproject.toml (used by CI)
set -euo pipefail
cd "$(dirname "$0")/.."

export_to() { # <outfile> [extra uv export args...]
    local out=$1
    shift
    uv export --frozen --no-emit-project --no-hashes --no-header "$@" >"$out"
}

if [[ "${1:-}" == "--check" ]]; then
    uv lock --check
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    export_to "$tmp/requirements.txt" --no-dev
    export_to "$tmp/requirements-dev.txt" --no-dev --extra dev
    status=0
    for f in requirements.txt requirements-dev.txt; do
        if ! diff -u "$f" "$tmp/$f"; then
            echo "::error::$f is out of date with uv.lock; run scripts/export_requirements.sh" >&2
            status=1
        fi
    done
    exit $status
fi

uv lock --check
export_to requirements.txt --no-dev
export_to requirements-dev.txt --no-dev --extra dev
