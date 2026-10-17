"""FastAPI backend application for AnnotateR.

Integrates with the verified core engines (Polars-Bio, Bedtools), format parsers,
and coordinate normalizers, serving REST endpoints for the modern React frontend.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from streamlit_app.api_sessions import (
    SESSION_COOKIE_NAME,
    Session,
    SessionStore,
    open_private_storage,
)

from streamlit_app.config import Settings
from streamlit_app.core import (
    CanonicalSchemaError,
    CustomParser,
    FormatDetector,
    VCFExportError,
    build_annotated_vcf,
    coordinate_system_for,
    extension_authoritative_for,
    normalize_intervals,
    parse_and_normalize,
)
from streamlit_app.core.chrom_registry import (
    assembly_options,
    find_assembly,
    load_catalog,
)
from streamlit_app.core.engine_registry import (
    DEFAULT_ENGINE,
    ENGINE_DESCRIPTIONS,
    ENGINE_LABELS,
    ENGINE_OPTIONS,
    engine_available,
    unavailable_message,
)
from streamlit_app.core.execution import (
    AnnotationError,
    AnnotationExecutionError,
    AnnotationRequest,
    execute_annotation as execute_annotation_core,
)
from streamlit_app.core.vcf_contigs import ChromosomeContigCollisionError
from streamlit_app.utils import get_example_data_path

app = FastAPI(
    title="AnnotateR API",
    version=Settings.VERSION,
    description="High-performance genomic coordinate annotation and interval overlap analysis API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Per-session request state (replaces the previous process-global cache)
# ---------------------------------------------------------------------------
#: Server-side, bounded, thread-safe store of per-session state. Each browser
#: receives its own opaque token (HttpOnly cookie); no request can reach
#: another session's state. See streamlit_app/api_sessions for the model and
#: the single-worker deployment constraint.
store = SessionStore()
_SESSION_TTL_SECONDS = int(store.ttl_seconds)


def _cookie_is_secure(request: Request) -> bool:
    """True when the request reached us over HTTPS (directly or via proxy)."""
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded.split(",")[0].strip().lower() == "https":
        return True
    return request.url.scheme == "https"


def get_session(request: Request) -> Session:
    """Resolve (or lazily create) the session owned by this request's cookie.

    The session is keyed only by the server-issued token in the cookie; no
    endpoint accepts a session identifier as input, so a request can never
    address another user's state.
    """
    existing = getattr(request.state, "session", None)
    if existing is not None:
        return existing
    session = store.get(request.cookies.get(SESSION_COOKIE_NAME))
    if session is None:
        session = store.create()
        # The middleware below attaches the cookie once the response exists.
        request.state.new_session_token = session.token
    request.state.session = session
    return session


@app.middleware("http")
async def _issue_session_cookie(request: Request, call_next):
    """Attach the session cookie to responses that created a new session."""
    response = await call_next(request)
    token = getattr(request.state, "new_session_token", None)
    if token:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=_SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=_cookie_is_secure(request),
            path="/",
        )
    return response


def _clean_df_for_json(df: pd.DataFrame, max_rows: int = 500) -> List[Dict[str, Any]]:
    """Convert dataframe to JSON-safe dictionary, sanitizing NaNs and infinities."""
    subset = df.head(max_rows).copy()
    subset = subset.replace({float("nan"): None, float("inf"): None, float("-inf"): None})
    return subset.to_dict(orient="records")


# ---------------------------------------------------------------------------
# API Routes
#
# VCF export is the shared, framework-independent writer in
# streamlit_app.core.vcf_export (``build_annotated_vcf``); this module keeps
# no second implementation.
# ---------------------------------------------------------------------------

@app.get("/api/meta")
def get_metadata():
    """Returns application metadata, available engines, and operation presets."""
    engines = []
    active_default = None
    for key, label in ENGINE_OPTIONS:
        avail = engine_available(key)
        if avail and active_default is None:
            active_default = key
        engines.append({
            "key": key,
            "label": label,
            "available": avail,
            "description": ENGINE_DESCRIPTIONS.get(key, ""),
            "unavailable_message": unavailable_message(key) if not avail else None,
        })

    catalog = load_catalog()
    assemblies = []
    for info in catalog:
        assemblies.append({
            "id": info.canonical_id,
            "display_label": info.display_label,
            "ucsc_db": info.ucsc_db,
            "organism": info.organism,
            "scientific_name": info.scientific_name,
        })

    return {
        "app_name": Settings.APP_NAME,
        "version": Settings.VERSION,
        "default_engine": active_default or DEFAULT_ENGINE,
        "engines": engines,
        "modes": [
            {"key": k, "label": k.title(), "description": v["description"]}
            for k, v in Settings.ANNOTATION_MODES.items()
        ],
        "feature_types": ["gene", "transcript", "exon", "CDS", "5' UTR", "3' UTR", "start_codon", "stop_codon"],
        "coord_systems": ["Auto-detect", "0-based (BED)", "1-based (GFF/GTF/VCF)"],
        "naming_options": [
            {"key": None, "label": "Keep original names"},
            {"key": "ensembl", "label": "Ensembl names"},
            {"key": "ucsc", "label": "UCSC names"},
            {"key": "refseq", "label": "NCBI RefSeq accessions"},
            {"key": "genbank", "label": "GenBank accessions"},
            {"key": "assembly", "label": "Assembly names"},
        ],
        "assemblies": assemblies,
    }


@app.get("/api/sample-datasets")
def list_sample_datasets():
    """Lists available pre-bundled sample datasets."""
    return [
        {
            "id": "gene_overlap",
            "name": "Gene Overlap Analysis",
            "query_file": "example_coordinates.bed",
            "annot_file": "example_annotations.gff3",
            "description": "Exemplary BED query intervals matched against Ensembl GFF3 gene models.",
            "mode": "overlap",
        },
        {
            "id": "closest_variants",
            "name": "Closest Variants Proximity",
            "query_file": "example_closest_variants.vcf",
            "annot_file": "example_closest_annotations.gff3",
            "description": "High-throughput VCF variation dataset paired with nearest gene proximity search.",
            "mode": "closest",
        },
        {
            "id": "stranded_features",
            "name": "Strand-Specific Features",
            "query_file": "example_strand_coordinates.bed",
            "annot_file": "example_strand_annotations.gff3",
            "description": "Strand-aware genomic intervals filtering for antisense/sense overlaps.",
            "mode": "overlap",
        },
    ]


@app.post("/api/load-sample")
def load_sample(sample_id: str = Form(...), session: Session = Depends(get_session)):
    """Loads a pre-bundled sample dataset into the active working state."""
    samples = {
        "gene_overlap": ("example_coordinates.bed", "example_annotations.gff3"),
        "closest_variants": ("example_closest_variants.vcf", "example_closest_annotations.gff3"),
        "stranded_features": ("example_strand_coordinates.bed", "example_strand_annotations.gff3"),
    }
    if sample_id not in samples:
        raise HTTPException(status_code=404, detail="Sample dataset not found")

    q_name, a_name = samples[sample_id]
    q_path = get_example_data_path(q_name)
    a_path = get_example_data_path(a_name)

    # Parse query
    q_fmt = FormatDetector.detect(str(q_path))
    q_df = parse_and_normalize(str(q_path), fmt=q_fmt)

    # Parse annotation
    a_fmt = FormatDetector.detect(str(a_path))
    a_df = parse_and_normalize(str(a_path), fmt=a_fmt)

    # Store in this session only
    session.data["query"] = {
        "filename": q_name,
        "format": q_fmt,
        "df": q_df,
        "rows": len(q_df),
        "columns": list(q_df.columns),
        "vcf_header_lines": q_df.attrs.get("vcf_header_lines"),
    }
    session.data["annot"] = {
        "filename": a_name,
        "format": a_fmt,
        "df": a_df,
        "rows": len(a_df),
        "columns": list(a_df.columns),
    }

    return {
        "status": "success",
        "query": {
            "filename": q_name,
            "format": q_fmt,
            "total_rows": len(q_df),
            "columns": list(q_df.columns),
            "preview": _clean_df_for_json(q_df, 50),
        },
        "annot": {
            "filename": a_name,
            "format": a_fmt,
            "total_rows": len(a_df),
            "columns": list(a_df.columns),
            "preview": _clean_df_for_json(a_df, 50),
        },
    }


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    role: str = Form(...),  # 'query' or 'annot'
    coord_system: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    """Uploads and parses a genomic interval file."""
    if role not in ("query", "annot"):
        raise HTTPException(status_code=400, detail="Role must be 'query' or 'annot'")

    # The client filename is never used as a path component: the file is
    # stored under a server-generated name inside a private temp directory,
    # preserving only a validated extension (see api_sessions.safe_extension).
    temp_dir = Path(tempfile.mkdtemp(prefix="annotater-upload-"))
    fd, temp_path = open_private_storage(temp_dir, file.filename)
    try:
        max_bytes = Settings.get_max_file_size_bytes()
        total = 0
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds the {Settings.MAX_FILE_SIZE_MB} MB limit",
                    )
                handle.write(chunk)

        fmt = FormatDetector.detect(str(temp_path))
        declared = None
        if coord_system and "0-based" in coord_system:
            declared = "0-based"
        elif coord_system and "1-based" in coord_system:
            declared = "1-based"

        if fmt == "custom":
            df = CustomParser.parse(str(temp_path))
            # A custom coordinate file always requires an explicit column
            # mapping: the declared coordinate system cannot be inferred from
            # the file (Streamlit behaves the same way). A custom annotation
            # is normalized in place when it already exposes the canonical
            # columns.
            needs_mapping = role == "query" or not all(
                c in df.columns for c in ("chr", "start", "end")
            )
            if not needs_mapping and role == "annot":
                df = normalize_intervals(df, coordinate_system=declared or "0-based")
        else:
            df = parse_and_normalize(str(temp_path), fmt=fmt, declared_system=declared)
            needs_mapping = False

        session.data[role] = {
            "filename": file.filename,
            "format": fmt,
            "df": df,
            "rows": len(df),
            "columns": list(df.columns),
            "needs_mapping": needs_mapping,
            "vcf_header_lines": df.attrs.get("vcf_header_lines"),
        }

        return {
            "status": "success",
            "role": role,
            "filename": file.filename,
            "format": fmt,
            "total_rows": len(df),
            "columns": list(df.columns),
            "needs_mapping": needs_mapping,
            "preview": _clean_df_for_json(df, 50),
        }
    except HTTPException:
        raise
    except Exception as exc:
        # User-input failures produce a clear, bounded error; server-side
        # paths are scrubbed so they are never echoed to the client.
        detail = str(exc).replace(str(temp_path), "the uploaded file")
        detail = detail.replace(str(temp_dir), "the uploaded file")
        raise HTTPException(status_code=400, detail=detail)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class ColumnMappingRequest(BaseModel):
    chr_col: str
    start_col: str
    # ``None`` marks a single-position file: each row becomes a one-base
    # interval in the declared coordinate system (mirrors the Streamlit
    # "None (single positions)" choice).
    end_col: Optional[str] = None
    strand_col: Optional[str] = None
    coord_system: str = "0-based"


def _declared_coordinate_system(option: Optional[str]) -> str:
    """UI coordinate-system selector -> explicit system.

    Only an explicit ``1-based`` declaration selects 1-based; everything else
    (including ``Auto-detect``) defaults to ``0-based``, exactly as the
    Streamlit app resolves it for custom files.
    """
    if option and option.startswith("1-based"):
        return "1-based"
    return "0-based"


@app.post("/api/apply-mapping")
def apply_mapping(req: ColumnMappingRequest, session: Session = Depends(get_session)):
    """Applies custom column mappings to a delimited coordinate file.

    Uses the same core building blocks as the Streamlit app
    (``CustomParser.map_columns`` + ``normalize_intervals``): chromosome,
    start, end (or single position) and optional strand are selected from the
    user's columns; every other column is preserved as metadata.
    """
    if "query" not in session.data:
        raise HTTPException(status_code=400, detail="No query dataset loaded")

    raw_df = session.data["query"]["df"]
    columns = list(raw_df.columns)
    end_col = req.end_col or None
    strand_col = req.strand_col or None

    requested = [("chr_col", req.chr_col), ("start_col", req.start_col)]
    if end_col is not None:
        requested.append(("end_col", end_col))
    if strand_col is not None:
        requested.append(("strand_col", strand_col))
    for field_name, column in requested:
        if column not in columns:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} {column!r} is not a column of the query file",
            )

    system = _declared_coordinate_system(req.coord_system)
    unmapped_cols = [
        c for c in columns
        if c not in (req.chr_col, req.start_col, end_col, strand_col)
    ]

    try:
        mapped_df = CustomParser.map_columns(
            raw_df, req.chr_col, req.start_col, end_col, unmapped_cols
        )
        if strand_col is not None:
            mapped_df["strand"] = raw_df[strand_col]
        if end_col is None:
            # A single position is exactly one base in the declared source
            # system (see the Streamlit mapping UI for the rationale).
            start_numeric = pd.to_numeric(mapped_df["start"], errors="coerce")
            mapped_df["end"] = (
                start_numeric if system == "1-based" else start_numeric + 1
            )
        mapped_df = normalize_intervals(mapped_df, coordinate_system=system)
    except (CanonicalSchemaError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Column mapping failed: {exc}")

    session.data["query"]["df"] = mapped_df
    session.data["query"]["needs_mapping"] = False
    session.data["query"]["columns"] = list(mapped_df.columns)
    session.data["query"]["rows"] = len(mapped_df)
    return {
        "status": "success",
        "total_rows": len(mapped_df),
        "columns": list(mapped_df.columns),
        "preview": _clean_df_for_json(mapped_df, 50),
    }


class ExecutionRequest(BaseModel):
    engine: str = "bedtools"
    mode: str = "overlap"
    join: str = "left"
    feature_types: List[str] = ["gene"]
    use_strand: bool = False
    min_overlap: float = 0.0
    assembly: Optional[str] = None
    chr_naming: Optional[str] = None


@app.post("/api/execute")
def execute_annotation(req: ExecutionRequest, session: Session = Depends(get_session)):
    """Executes the genomic interval annotation pipeline.

    HTTP translation only: the single scientific workflow lives in the shared
    ``streamlit_app.core.execution`` service (the same one the Streamlit GUI
    uses). This endpoint maps the request onto that service and serializes the
    outcome; it contains no scientific logic of its own.
    """
    if "query" not in session.data or "annot" not in session.data:
        raise HTTPException(status_code=400, detail="Both query and annotation datasets must be loaded")

    query = session.data["query"]
    annot = session.data["annot"]

    request = AnnotationRequest(
        query=query["df"],
        annotation=annot["df"],
        annotation_format=annot.get("format"),
        engine=req.engine,
        mode=req.mode,
        join=req.join,
        use_strand=req.use_strand,
        min_overlap=req.min_overlap,
        feature_types=tuple(req.feature_types or ()),
        chr_naming=req.chr_naming,
        assembly=req.assembly,
        coord_vcf_header_lines=query.get("vcf_header_lines"),
    )

    try:
        outcome = execute_annotation_core(request)
    except AnnotationExecutionError as exc:
        # Backend/canonicalization failure is propagated explicitly, never
        # reported as an empty result.
        raise HTTPException(status_code=500, detail=exc.message)
    except AnnotationError as exc:
        raise HTTPException(status_code=400, detail=exc.message)

    result_df = outcome.result_df

    matched = int(result_df["has_overlap"].sum()) if "has_overlap" in result_df.columns else len(result_df)
    unmatched = len(result_df) - matched
    match_rate = (matched / max(1, len(outcome.coord_df))) * 100

    # Store result in this session only. The scientific report fields below
    # are ones the previous response contract could not carry; they are kept
    # for the results/export endpoints and surfaced to the client.
    session.data["result"] = {
        "df": result_df,
        "coord_format": query.get("format"),
        "vcf_header_lines": outcome.vcf_header_lines,
        "vcf_contig_renames": dict(outcome.vcf_contig_renames),
        "chromosome_normalization": (
            outcome.chromosome_normalization.as_dict()
            if outcome.chromosome_normalization is not None
            else None
        ),
        "warnings": [warning.as_dict() for warning in outcome.warnings],
        "feature_filter": (
            outcome.feature_filter.as_dict()
            if outcome.feature_filter is not None
            else None
        ),
        "elapsed": outcome.elapsed_seconds,
        "join": outcome.join,
        "mode": outcome.mode,
    }

    # Generate Chart Data
    chr_dist = []
    if "coord_chr" in result_df.columns:
        counts = result_df["coord_chr"].value_counts().head(25)
        chr_dist = [{"chromosome": str(k), "intervals": int(v)} for k, v in counts.items()]

    feature_dist = []
    if "annot_feature" in result_df.columns and result_df["annot_feature"].notna().any():
        f_counts = result_df["annot_feature"].dropna().value_counts().head(10)
        feature_dist = [{"feature": str(k), "count": int(v)} for k, v in f_counts.items()]

    distance_dist = []
    if req.mode == "closest" and "distance" in result_df.columns:
        valid_d = result_df["distance"].dropna()
        if not valid_d.empty:
            hist, bin_edges = pd.cut(valid_d, bins=15, retbins=True)
            dist_counts = hist.value_counts().sort_index()
            distance_dist = [
                {"range": f"{int(iv.left):,} - {int(iv.right):,}", "count": int(c)}
                for iv, c in dist_counts.items()
            ]

    return {
        "status": "success",
        "stats": {
            "query_count": len(outcome.coord_df),
            "result_count": len(result_df),
            "matched_count": matched,
            "unmatched_count": unmatched,
            "match_rate": round(match_rate, 2),
            "elapsed_seconds": round(outcome.elapsed_seconds, 4),
            "engine": outcome.engine,
            "mode": outcome.mode,
            "join": outcome.join,
        },
        "charts": {
            "chromosome_distribution": chr_dist,
            "feature_distribution": feature_dist,
            "distance_distribution": distance_dist,
            "match_ratio": [
                {"name": "Matched", "value": matched},
                {"name": "Unmatched", "value": unmatched},
            ],
        },
        # Scientific report fields the previous response contract could not
        # carry (previously discarded); exposed additively so no run
        # information is lost. ``chromosome_normalization`` is null when
        # names were kept as provided.
        "warnings": [warning.as_dict() for warning in outcome.warnings],
        "chromosome_normalization": (
            outcome.chromosome_normalization.as_dict()
            if outcome.chromosome_normalization is not None
            else None
        ),
        "feature_filter": (
            outcome.feature_filter.as_dict()
            if outcome.feature_filter is not None
            else None
        ),
        "columns": list(result_df.columns),
        "total_rows": len(result_df),
        "preview": _clean_df_for_json(result_df, 100),
    }


@app.get("/api/results/data")
def get_results_data(
    filter_type: str = "all",
    page: int = 1,
    page_size: int = 50,
    session: Session = Depends(get_session),
):
    """Fetches paginated results with filter support (all, matched, unmatched)."""
    if "result" not in session.data:
        raise HTTPException(status_code=404, detail="No execution results available")

    df = session.data["result"]["df"]
    if filter_type == "matched" and "has_overlap" in df.columns:
        filtered = df[df["has_overlap"] == True]
    elif filter_type == "unmatched" and "has_overlap" in df.columns:
        filtered = df[df["has_overlap"] == False]
    else:
        filtered = df

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    sliced = filtered.iloc[start_idx:end_idx]

    return {
        "total_rows": len(filtered),
        "page": page,
        "page_size": page_size,
        "total_pages": (len(filtered) + page_size - 1) // page_size,
        "rows": _clean_df_for_json(sliced, page_size),
    }


@app.get("/api/export/{fmt}")
def export_results(fmt: str, filter_type: str = "all", session: Session = Depends(get_session)):
    """Downloads results in CSV, TSV, Excel, or VCF format."""
    if "result" not in session.data:
        raise HTTPException(status_code=404, detail="No results found to export")

    res = session.data["result"]
    df = res["df"]
    if filter_type == "matched" and "has_overlap" in df.columns:
        export_df = df[df["has_overlap"] == True]
    elif filter_type == "unmatched" and "has_overlap" in df.columns:
        export_df = df[df["has_overlap"] == False]
    else:
        export_df = df

    if fmt == "csv":
        csv_data = export_df.to_csv(index=False)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=annotated_intervals.csv"},
        )
    elif fmt == "tsv":
        tsv_data = export_df.to_csv(index=False, sep="\t")
        return Response(
            content=tsv_data,
            media_type="text/tab-separated-values",
            headers={"Content-Disposition": "attachment; filename=annotated_intervals.tsv"},
        )
    elif fmt == "xlsx":
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="Annotated")
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=annotated_intervals.xlsx"},
        )
    elif fmt == "vcf":
        try:
            vcf_str = build_annotated_vcf(
                export_df,
                original_header_lines=res.get("vcf_header_lines"),
                contig_renames=res.get("vcf_contig_renames"),
            )
        except ChromosomeContigCollisionError:
            raise HTTPException(
                status_code=409,
                detail=(
                    "VCF export unavailable: some normalized chromosome "
                    "names share contig metadata that conflicts. Choose a "
                    "different source assembly for this input."
                ),
            )
        except VCFExportError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return Response(
            content=vcf_str,
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=annotated_variants.vcf"},
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format {fmt}")


# ---------------------------------------------------------------------------
# Mount Built Frontend Static Files (if dist exists)
# ---------------------------------------------------------------------------
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
