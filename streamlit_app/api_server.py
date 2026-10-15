"""FastAPI backend application for AnnotateR.

Integrates with the verified core engines (Polars-Bio, Bedtools), format parsers,
and coordinate normalizers, serving REST endpoints for the modern React frontend.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from streamlit_app.config import Settings
from streamlit_app.core import (
    CustomParser,
    FormatDetector,
    canonicalize_annotation_result,
    coordinate_system_for,
    extension_authoritative_for,
    normalize_intervals,
    parse_and_normalize,
)
from streamlit_app.core.chrom_registry import (
    assembly_options,
    find_assembly,
    load_catalog,
    load_registry,
)
from streamlit_app.core.chromosome_inputs import normalize_input_chromosomes
from streamlit_app.core.vcf_contigs import header_contig_renames
from streamlit_app.core.engine_registry import (
    DEFAULT_ENGINE,
    ENGINE_DESCRIPTIONS,
    ENGINE_LABELS,
    ENGINE_OPTIONS,
    build_engine,
    engine_available,
    unavailable_message,
)
from streamlit_app.utils import DataValidator, get_example_data_path

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
# In-Memory Cache for Parsed Datasets and Run Results (keyed by token/id)
# ---------------------------------------------------------------------------
_DATA_CACHE: Dict[str, Any] = {}


def _clean_df_for_json(df: pd.DataFrame, max_rows: int = 500) -> List[Dict[str, Any]]:
    """Convert dataframe to JSON-safe dictionary, sanitizing NaNs and infinities."""
    subset = df.head(max_rows).copy()
    subset = subset.replace({float("nan"): None, float("inf"): None, float("-inf"): None})
    return subset.to_dict(orient="records")


def _vcf_info_key(col_name: str) -> str:
    key = col_name.upper()
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in key)
    return f"AN_{cleaned}" if not cleaned.startswith("AN_") else cleaned


def _escape_vcf_info_value(val: str) -> str:
    return str(val).replace(" ", "_").replace(";", "%3B").replace("=", "%3D").replace(",", "%2C")


def _chrom_renames(before: pd.Series, after: pd.Series) -> Dict[str, str]:
    renames = {}
    for old_val, new_val in zip(before, after):
        old_s, new_s = str(old_val), str(new_val)
        if old_s != new_s and old_s not in renames:
            renames[old_s] = new_s
    return renames


def convert_df_to_vcf(df: pd.DataFrame, original_header_lines=None, contig_renames=None) -> str:
    lines = []
    if original_header_lines:
        for raw in original_header_lines:
            line = str(raw).strip()
            if not line:
                continue
            if contig_renames and line.startswith("##contig=<") and "ID=" in line:
                for old_id, new_id in contig_renames.items():
                    if f"ID={old_id}," in line or f"ID={old_id}>" in line:
                        line = line.replace(f"ID={old_id},", f"ID={new_id},").replace(f"ID={old_id}>", f"ID={new_id}>")
                        break
            lines.append(line)
    else:
        lines.append("##fileformat=VCFv4.2")

    annot_cols = [c for c in df.columns if c.startswith("annot_")]
    if "distance" in df.columns and "distance" not in annot_cols:
        annot_cols.append("distance")
    if "has_overlap" in df.columns and "annot_has_overlap" not in annot_cols:
        annot_cols.append("has_overlap")

    for col in annot_cols:
        key = _vcf_info_key(col)
        lines.append(f'##INFO=<ID={key},Number=1,Type=String,Description="AnnotateR: {col}">')

    sample_cols = [c for c in df.columns if c.startswith("coord_sample_")]
    sample_names = [c.replace("coord_sample_", "") for c in sample_cols]

    vcf_cols = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
    if sample_cols:
        vcf_cols.append("FORMAT")
        vcf_cols.extend(sample_names)
    lines.append("\t".join(vcf_cols))

    for _, row in df.iterrows():
        chrom = str(row.get("coord_chr", "."))
        pos = str(int(row.get("coord_start", 0)) + 1)
        id_val = str(row.get("coord_id", "."))
        ref = str(row.get("coord_ref", "N"))
        alt = str(row.get("coord_alt", "."))
        qual = str(row.get("coord_qual", "."))
        filt = str(row.get("coord_filter", "."))

        orig_info = str(row.get("coord_info", "."))
        info_parts = [orig_info] if orig_info != "." else []

        for col in annot_cols:
            val = row.get(col)
            if val is not None and not pd.isna(val) and str(val).strip() not in ("", ".", "nan", "NA", "<NA>"):
                k = _vcf_info_key(col)
                v = _escape_vcf_info_value(str(val))
                info_parts.append(f"{k}={v}")

        info_str = ";".join(info_parts) if info_parts else "."
        rec = [chrom, pos, id_val, ref, alt, qual, filt, info_str]

        if sample_cols:
            rec.append("GT")
            for c in sample_cols:
                rec.append(str(row.get(c, "./.")))

        lines.append("\t".join(rec))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# API Routes
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
def load_sample(sample_id: str = Form(...)):
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

    # Cache
    _DATA_CACHE["query"] = {
        "filename": q_name,
        "format": q_fmt,
        "df": q_df,
        "rows": len(q_df),
        "columns": list(q_df.columns),
        "vcf_header_lines": q_df.attrs.get("vcf_header_lines"),
    }
    _DATA_CACHE["annot"] = {
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
):
    """Uploads and parses a genomic interval file."""
    temp_dir = tempfile.mkdtemp()
    temp_path = Path(temp_dir) / file.filename
    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        fmt = FormatDetector.detect(str(temp_path))
        declared = None
        if coord_system and "0-based" in coord_system:
            declared = "0-based"
        elif coord_system and "1-based" in coord_system:
            declared = "1-based"

        if fmt == "custom":
            df = CustomParser.parse(str(temp_path))
            needs_mapping = not all(c in df.columns for c in ("chr", "start", "end"))
            if not needs_mapping and role == "annot":
                df = normalize_intervals(df, coordinate_system=declared or "0-based")
        else:
            df = parse_and_normalize(str(temp_path), fmt=fmt, declared_system=declared)
            needs_mapping = False

        _DATA_CACHE[role] = {
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


class ColumnMappingRequest(BaseModel):
    chr_col: str
    start_col: str
    end_col: str
    strand_col: Optional[str] = None
    coord_system: str = "0-based"


@app.post("/api/apply-mapping")
def apply_mapping(req: ColumnMappingRequest):
    """Applies custom column mappings to delimited files."""
    if "query" not in _DATA_CACHE:
        raise HTTPException(status_code=400, detail="No query dataset loaded")

    raw_df = _DATA_CACHE["query"]["df"]
    mapping = {"chr": req.chr_col, "start": req.start_col, "end": req.end_col}
    if req.strand_col:
        mapping["strand"] = req.strand_col

    declared = "0-based" if "0-based" in req.coord_system else "1-based"
    parser = CustomParser(declared_system=declared)
    try:
        mapped_df = parser.apply_mapping(raw_df, mapping)
        _DATA_CACHE["query"]["df"] = mapped_df
        _DATA_CACHE["query"]["needs_mapping"] = False
        _DATA_CACHE["query"]["columns"] = list(mapped_df.columns)
        return {
            "status": "success",
            "total_rows": len(mapped_df),
            "columns": list(mapped_df.columns),
            "preview": _clean_df_for_json(mapped_df, 50),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
def execute_annotation(req: ExecutionRequest):
    """Executes the genomic interval annotation pipeline."""
    if "query" not in _DATA_CACHE or "annot" not in _DATA_CACHE:
        raise HTTPException(status_code=400, detail="Both query and annotation datasets must be loaded")

    coord_df = _DATA_CACHE["query"]["df"].copy()
    annot_df = _DATA_CACHE["annot"]["df"].copy()
    annot_format = _DATA_CACHE["annot"]["format"]

    is_valid, err = DataValidator.validate_coordinates(coord_df)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Query coordinates validation failed: {err}")
    is_valid, err = DataValidator.validate_coordinates(annot_df)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Annotation reference validation failed: {err}")

    # Feature filtering
    if annot_format in ("gff", "gtf") and req.feature_types and "feature" in annot_df.columns:
        annot_df = annot_df[annot_df["feature"].isin(req.feature_types)].copy()
        if len(annot_df) == 0:
            raise HTTPException(status_code=400, detail="No annotation features match selected feature filter")

    # Assembly-aware chromosome normalization (SPEC 5.1 & RC3)
    vcf_contig_renames = {}
    if req.chr_naming is not None:
        if req.assembly is None:
            raise HTTPException(status_code=400, detail="Please select a genome assembly before normalizing chromosome names.")
        try:
            registry = load_registry(req.assembly)
            normalized = normalize_input_chromosomes(
                coord_df,
                annot_df,
                registry=registry,
                target=req.chr_naming,
            )
            coord_df, annot_df = normalized.coord_df, normalized.annot_df
            vcf_contig_renames = dict(normalized.coord_renames)

            vcf_headers = _DATA_CACHE["query"].get("vcf_header_lines")
            if vcf_headers:
                vcf_contig_renames = {
                    **header_contig_renames(vcf_headers, registry, req.chr_naming),
                    **vcf_contig_renames,
                }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Chromosome normalization error: {exc}")

    t0 = time.perf_counter()
    try:
        min_ov = req.min_overlap if req.mode == "overlap" else None
        engine = build_engine(
            req.engine,
            mode=req.mode,
            use_strand=req.use_strand,
            min_overlap=min_ov,
        )
        raw_result = engine.intersect(coord_df, annot_df, how=req.join)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Engine annotation execution failed: {exc}")

    try:
        result_df = canonicalize_annotation_result(
            raw_result,
            coord_df,
            annot_df,
            extra_columns=("distance",) if req.mode == "closest" else (),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Canonicalization failed: {exc}")
    elapsed = time.perf_counter() - t0

    matched = int(result_df["has_overlap"].sum()) if "has_overlap" in result_df.columns else len(result_df)
    unmatched = len(result_df) - matched
    match_rate = (matched / max(1, len(coord_df))) * 100

    # Cache result
    _DATA_CACHE["result"] = {
        "df": result_df,
        "coord_format": _DATA_CACHE["query"]["format"],
        "vcf_header_lines": _DATA_CACHE["query"].get("vcf_header_lines"),
        "vcf_contig_renames": vcf_contig_renames,
        "elapsed": elapsed,
        "join": req.join,
        "mode": req.mode,
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
            "query_count": len(coord_df),
            "result_count": len(result_df),
            "matched_count": matched,
            "unmatched_count": unmatched,
            "match_rate": round(match_rate, 2),
            "elapsed_seconds": round(elapsed, 4),
            "engine": req.engine,
            "mode": req.mode,
            "join": req.join,
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
        "columns": list(result_df.columns),
        "total_rows": len(result_df),
        "preview": _clean_df_for_json(result_df, 100),
    }


@app.get("/api/results/data")
def get_results_data(filter_type: str = "all", page: int = 1, page_size: int = 50):
    """Fetches paginated results with filter support (all, matched, unmatched)."""
    if "result" not in _DATA_CACHE:
        raise HTTPException(status_code=404, detail="No execution results available")

    df = _DATA_CACHE["result"]["df"]
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
def export_results(fmt: str, filter_type: str = "all"):
    """Downloads results in CSV, TSV, Excel, or VCF format."""
    if "result" not in _DATA_CACHE:
        raise HTTPException(status_code=404, detail="No results found to export")

    res = _DATA_CACHE["result"]
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
        vcf_str = convert_df_to_vcf(
            export_df,
            original_header_lines=res.get("vcf_header_lines"),
            contig_renames=res.get("vcf_contig_renames"),
        )
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
