"""
Annotation engine for coordinate intersection

Uses pybedtools for fast, memory-efficient genomic coordinate operations
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union
import tempfile

import numpy as np
import pandas as pd
import polars as pl
import polars_bio as pb
import pybedtools
from .schema import (
    CANONICAL_MISSING,
    HAS_OVERLAP_COLUMN,
    CanonicalSchemaError,
    canonical_result_columns,
    validate_canonical_interval_table,
)

logger = logging.getLogger(__name__)


class AnnotationEngine(ABC):
    """
    Abstract base class for annotation engines
    """
    
    def __init__(
        self,
        use_strand: bool = False,
        min_overlap: Optional[float] = None,
        mode: Literal["overlap", "contains", "within", "closest"] = "overlap"
    ):
        self.use_strand = use_strand
        self.min_overlap = min_overlap
        self.mode = mode
    
    @abstractmethod
    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        pass


class BedtoolsEngine(AnnotationEngine):
    """
    Standard coordinate intersection using pybedtools
    """
    
    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        """Performed intersection using bedtools"""
        
        # Validate (simple check)
        if coord_df.empty or annot_df.empty:
            return pd.DataFrame()

        # Create temporary BED files
        coord_bed = self._df_to_bedtool(coord_df, prefix="coords")
        annot_bed = self._df_to_bedtool(annot_df, prefix="annot")
        
        try:
            if self.mode == "overlap":
                result = self._intersect_overlap(coord_bed, annot_bed, how)
            elif self.mode == "contains":
                result = self._intersect_contains(coord_bed, annot_bed)
            elif self.mode == "within":
                result = self._intersect_within(coord_bed, annot_bed)
            elif self.mode == "closest":
                result = self._find_closest(coord_bed, annot_bed)
            else:
                raise ValueError(f"Unknown mode: {self.mode}")
            
            # Convert result to DataFrame
            result_df = self._bedtool_to_df(result, coord_df, annot_df)
            
        finally:
            pybedtools.cleanup()
        
        return result_df

    def _df_to_bedtool(self, df: pd.DataFrame, prefix: str = "temp") -> pybedtools.BedTool:
        """Convert DataFrame to BedTool object"""
        bed_df = df[['chr', 'start', 'end']].copy()
        bed_df['start'] = bed_df['start'].astype(int)
        bed_df['end'] = bed_df['end'].astype(int)
        
        # Keep extra columns
        extra_cols = [col for col in df.columns if col not in ['chr', 'start', 'end']]
        for col in extra_cols[:9]:
            bed_df[col] = df[col].astype(str).fillna('.')
        
        return pybedtools.BedTool.from_dataframe(bed_df)
    
    def _intersect_overlap(self, coord_bed, annot_bed, how):
        kwargs = {"wa": True, "wb": True, "s": self.use_strand}
        if self.min_overlap: kwargs["f"] = self.min_overlap
        if how == "left": kwargs["loj"] = True
        return coord_bed.intersect(annot_bed, **kwargs)
    
    def _intersect_contains(self, coord_bed, annot_bed):
        return coord_bed.intersect(annot_bed, wa=True, wb=True, f=1.0, s=self.use_strand)

    def _intersect_within(self, coord_bed, annot_bed):
        return coord_bed.intersect(annot_bed, wa=True, wb=True, F=1.0, s=self.use_strand)

    def _find_closest(self, coord_bed, annot_bed):
        return coord_bed.closest(annot_bed, d=True, t="first", s=self.use_strand)

    def _bedtool_to_df(self, bedtool, coord_df, annot_df):
        try:
            result_df = bedtool.to_dataframe(header=None)
        except Exception:
            return pd.DataFrame()
            
        if result_df.empty: return result_df
        
        # Build column names
        num_cols = len(result_df.columns)
        
        def get_cols(df):
            core = ['chr', 'start', 'end']
            extra = [c for c in df.columns if c not in core]
            return core + extra[:9]
            
        coord_cols = get_cols(coord_df)
        annot_cols = get_cols(annot_df)
        
        new_cols = []
        for c in coord_cols: new_cols.append(f"coord_{c}")
        for c in annot_cols: new_cols.append(f"annot_{c}")
        if self.mode == "closest": new_cols.append("distance")
        
        # Pad and assign
        final_cols = new_cols[:num_cols]
        while len(final_cols) < num_cols:
            final_cols.append(f"col_{len(final_cols)}")
            
        result_df.columns = final_cols
        
        # Add overlap status
        if 'annot_chr' in result_df.columns:
            # Check for generic 'no overlap' markers from bedtools left outer join (usually '.', -1)
            result_df['has_overlap'] = (result_df['annot_chr'] != '.') & \
                                       (result_df['annot_chr'].astype(str) != '-1')
        
        return result_df


_PB_INTERVAL_COLUMNS = ("chrom", "start", "end")
_PB_SUFFIXES = ("_1", "_2")
_PB_QUERY_ROW_ID = "_pb_query_row_id"
_PB_ANNOT_ROW_ID = "_pb_annot_row_id"
_PB_Q_ID_COLUMN = "_pb_q_id"
_PB_A_ID_COLUMN = "_pb_a_id"


class PolarsBioEngine(AnnotationEngine):
    """
    High-performance engine using Polars and Polars-Bio (Rust backend)

    Canonical result contract (SPEC 4.2; docs/engine-contract.md 4-8):

    - Canonical inputs (0-based half-open ``chr``/``start``/``end`` plus
      metadata) are validated, converted to polars frames, and stamped
      with the per-frame coordinate-system metadata
      ``coordinate_system_zero_based=True`` so interval operations
      interpret the data as 0-based half-open. No process-global
      polars-bio option is read or mutated.
    - Stable per-row identity columns (collision-safe names, Int64) are
      added to both inputs before the backend call. They drive the
      deterministic canonical ordering (query input order, then
      annotation input order) and the left-mode reconstruction of
      unmatched queries, and they are removed before public output.
    - ``pb.overlap`` / ``pb.nearest`` are invoked with explicit
      ``cols1``/``cols2`` and explicit suffixes. The raw backend output
      is mapped to the canonical ``coord_*``/``annot_*`` schema using
      the exact input schemas: provenance comes from input position,
      never from output suffix heuristics. A raw output whose columns do
      not match the expected mapping raises ``CanonicalSchemaError``
      instead of guessing.
    - Backend exceptions propagate to the caller. A valid no-match is
      not an exception: it remains a valid empty (0-row) result.
    """

    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        """Intersect canonical interval tables and return canonical results."""
        # Engine inputs MUST be canonical (SPEC 4.2): fail explicitly on
        # malformed input instead of returning a silent empty result.
        validate_canonical_interval_table(coord_df)
        validate_canonical_interval_table(annot_df)

        if self.mode == "overlap":
            return self._overlap(coord_df, annot_df, how)
        if self.mode == "closest":
            return self._nearest(coord_df, annot_df)
        if self.mode in ("contains", "within"):
            # Non-normative placeholder mapping (engine-contract 9/11):
            # plain overlap for now; _filter_fraction is a documented no-op.
            return self._filter_fraction(
                self._overlap(coord_df, annot_df, how), mode=self.mode
            )
        raise ValueError(f"Unknown mode: {self.mode}")

    # ------------------------------------------------------------------
    # Overlap (inner + left)
    # ------------------------------------------------------------------

    def _overlap(self, coord_df: pd.DataFrame, annot_df: pd.DataFrame, how: str) -> pd.DataFrame:
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _PB_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _PB_ANNOT_ROW_ID)
        q_frame = self._prepare_backend_frame(coord_df, q_id)
        a_frame = self._prepare_backend_frame(annot_df, a_id)

        logger.debug("Running pb.overlap on %d x %d rows", len(coord_df), len(annot_df))
        # Backend failures MUST propagate (SPEC 9.2): a valid no-match is
        # not an exception and remains a valid empty (0-row) result, but a
        # backend error must never be reported as "no matches".
        raw = pb.overlap(
            q_frame,
            a_frame,
            suffixes=_PB_SUFFIXES,
            cols1=list(_PB_INTERVAL_COLUMNS),
            cols2=list(_PB_INTERVAL_COLUMNS),
            output_type="polars.DataFrame",
        )

        return self._adapt_overlap_result(raw, coord_df, annot_df, how)

    def _adapt_overlap_result(
        self,
        raw: pl.DataFrame,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: str,
    ) -> pd.DataFrame:
        """Map raw pb.overlap output to the canonical result schema."""
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _PB_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _PB_ANNOT_ROW_ID)
        rename, expected = self._canonical_rename_map(q_meta, a_meta, q_id, a_id)

        # Empty raw result: no exception was raised, so this is a genuine
        # no-match (a valid empty result), not a swallowed backend error.
        if raw.is_empty():
            if how == "left" and len(coord_df) > 0:
                unmatched = self._unmatched_query_rows(
                    coord_df, q_meta, a_meta, list(range(len(coord_df)))
                )
                return unmatched[list(canonical_result_columns(coord_df, annot_df))]
            return pd.DataFrame()

        df = raw.to_pandas()
        missing = [c for c in expected if c not in df.columns]
        unexpected = [c for c in df.columns if c not in expected]
        if missing or unexpected:
            raise CanonicalSchemaError(
                "polars-bio raw output columns do not match the expected "
                "suffixed mapping; column provenance cannot be determined "
                f"explicitly. missing={missing}, unexpected={unexpected}"
            )
        df = df.rename(columns=rename)

        # Deterministic canonical ordering by input row identity (never by
        # genomic coordinate): query input order, then annotation input order.
        df = df.sort_values([_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN], kind="stable")
        df[HAS_OVERLAP_COLUMN] = True

        if how == "left":
            matched_ids = set(df[_PB_Q_ID_COLUMN].tolist())
            unmatched_positions = [
                i for i in range(len(coord_df)) if i not in matched_ids
            ]
            if unmatched_positions:
                unmatched = self._unmatched_query_rows(
                    coord_df, q_meta, a_meta, unmatched_positions
                )
                df = pd.concat([df, unmatched], ignore_index=True)
                df = df.sort_values([_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN], kind="stable")

        df = df.drop(columns=[_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN])
        return df[list(canonical_result_columns(coord_df, annot_df))]

    # ------------------------------------------------------------------
    # Closest (non-normative)
    # ------------------------------------------------------------------

    def _nearest(self, coord_df: pd.DataFrame, annot_df: pd.DataFrame) -> pd.DataFrame:
        q_meta = self._metadata_columns(coord_df)
        a_meta = self._metadata_columns(annot_df)
        q_id = self._row_id_column(coord_df.columns, _PB_QUERY_ROW_ID)
        a_id = self._row_id_column(annot_df.columns, _PB_ANNOT_ROW_ID)
        q_frame = self._prepare_backend_frame(coord_df, q_id)
        a_frame = self._prepare_backend_frame(annot_df, a_id)

        logger.debug("Running pb.nearest on %d x %d rows", len(coord_df), len(annot_df))
        # Backend failures MUST propagate (SPEC 9.2), same principle as
        # overlap: a valid no-match is a valid empty result, but a backend
        # exception must never be reported as "no matches".
        raw = pb.nearest(
            q_frame,
            a_frame,
            suffixes=_PB_SUFFIXES,
            cols1=list(_PB_INTERVAL_COLUMNS),
            cols2=list(_PB_INTERVAL_COLUMNS),
            output_type="polars.DataFrame",
        )

        if raw.is_empty():
            return pd.DataFrame()

        rename, expected = self._canonical_rename_map(q_meta, a_meta, q_id, a_id)
        df = raw.to_pandas()
        missing = [c for c in expected if c not in df.columns]
        # pb.nearest additionally emits an unsuffixed "distance" column.
        unexpected = [c for c in df.columns if c not in expected and c != "distance"]
        if missing or unexpected:
            raise CanonicalSchemaError(
                "polars-bio raw nearest output columns do not match the "
                "expected suffixed mapping; column provenance cannot be "
                f"determined explicitly. missing={missing}, unexpected={unexpected}"
            )
        df = df.rename(columns=rename)

        # When no annotation exists, pb.nearest still emits one row per
        # query with ALL annotation fields null (k=1, no neighbor). Those
        # rows do not represent a real match; drop them so closest mode
        # with an empty annotation table returns a genuinely empty result
        # (SPEC 9.2: a valid empty, not phantom "nearest" hits).
        df = df[df[_PB_A_ID_COLUMN].notna()].reset_index(drop=True)
        if df.empty:
            return pd.DataFrame()

        # One row per query row (k=1); order by query input position.
        df = df.sort_values(_PB_Q_ID_COLUMN, kind="stable")
        df[HAS_OVERLAP_COLUMN] = True
        df = df.drop(columns=[_PB_Q_ID_COLUMN, _PB_A_ID_COLUMN])
        columns = list(canonical_result_columns(coord_df, annot_df))
        if "distance" in df.columns:
            columns.append("distance")
        return df[columns]

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _filter_fraction(self, res: pd.DataFrame, mode: str) -> pd.DataFrame:
        # Non-normative contains/within placeholder (engine-contract 9/11):
        # no fractional filtering is applied yet; pass through unchanged.
        return res

    @staticmethod
    def _metadata_columns(df: pd.DataFrame) -> List[str]:
        """Metadata columns: every column except the canonical core."""
        return [c for c in df.columns if c not in ("chr", "start", "end")]

    @staticmethod
    def _row_id_column(columns, preferred: str) -> str:
        """Collision-safe internal row-identity column name."""
        name = preferred
        suffix = 2
        while name in columns:
            name = f"{preferred}_{suffix}"
            suffix += 1
        return name

    @staticmethod
    def _prepare_backend_frame(df: pd.DataFrame, row_id: str) -> pl.DataFrame:
        """
        Convert a canonical pandas table into a polars-bio backend frame.

        - renames ``chr`` to polars-bio's documented interval column name
          ``chrom``;
        - casts core columns to the documented dtypes;
        - appends a stable positional row-identity column (Int64);
        - stamps the per-frame coordinate-system metadata (0-based,
          half-open) so polars-bio operations interpret intervals
          half-open without any process-global option state.
        """
        frame = pl.from_pandas(df)
        frame = frame.rename({"chr": "chrom"})
        frame = frame.with_columns([
            pl.col("chrom").cast(pl.Utf8),
            pl.col("start").cast(pl.Int64),
            pl.col("end").cast(pl.Int64),
        ])
        frame = frame.with_row_index(row_id)
        frame = frame.with_columns(pl.col(row_id).cast(pl.Int64))
        frame.config_meta.set(coordinate_system_zero_based=True)
        return frame

    @staticmethod
    def _canonical_rename_map(q_meta, a_meta, q_id, a_id):
        """
        Explicit raw-output rename map derived from the input schemas.

        Returns (rename_dict, expected_raw_column_set). Provenance is
        defined by input position (which columns came from which input),
        never by output suffix heuristics.
        """
        s1, s2 = _PB_SUFFIXES
        rename = {
            f"chrom{s1}": "coord_chr",
            f"start{s1}": "coord_start",
            f"end{s1}": "coord_end",
            f"chrom{s2}": "annot_chr",
            f"start{s2}": "annot_start",
            f"end{s2}": "annot_end",
            f"{q_id}{s1}": _PB_Q_ID_COLUMN,
            f"{a_id}{s2}": _PB_A_ID_COLUMN,
        }
        for column in q_meta:
            rename[f"{column}{s1}"] = f"coord_{column}"
        for column in a_meta:
            rename[f"{column}{s2}"] = f"annot_{column}"
        return rename, set(rename)

    @staticmethod
    def _unmatched_query_rows(
        coord_df: pd.DataFrame, q_meta, a_meta, positions
    ) -> pd.DataFrame:
        """
        One canonical unmatched row per query position (left mode).

        Annot fields are the canonical missing value; the row-identity
        columns carry the query position and a sentinel -1 annotation
        position.
        """
        n = len(positions)
        sub = coord_df.iloc[positions]
        out = pd.DataFrame({
            "coord_chr": sub["chr"].to_numpy(),
            "coord_start": sub["start"].astype("int64").to_numpy(),
            "coord_end": sub["end"].astype("int64").to_numpy(),
        })
        for column in q_meta:
            out[f"coord_{column}"] = sub[column].to_numpy()
        out["annot_chr"] = pd.array([CANONICAL_MISSING] * n, dtype=object)
        out["annot_start"] = pd.array([CANONICAL_MISSING] * n, dtype="Int64")
        out["annot_end"] = pd.array([CANONICAL_MISSING] * n, dtype="Int64")
        for column in a_meta:
            out[f"annot_{column}"] = pd.array([CANONICAL_MISSING] * n, dtype=object)
        out[HAS_OVERLAP_COLUMN] = False
        out[_PB_Q_ID_COLUMN] = np.asarray(positions, dtype="int64")
        out[_PB_A_ID_COLUMN] = np.full(n, -1, dtype="int64")
        return out

def get_summary_stats(result_df: pd.DataFrame, coord_df: pd.DataFrame) -> Dict:
    """
    Generate summary statistics about annotation results
    (Standalone function now, or static method)
    """
    if result_df.empty:
        return {
            "total_coordinates": len(coord_df),
            "annotated_coordinates": 0,
            "total_annotations": 0,
            "unique_chromosomes": 0,
            "annotation_rate": 0.0
        }
    
    return {
        "total_coordinates": len(coord_df),
        "annotated_coordinates": result_df['coord_chr'].nunique() if 'coord_chr' in result_df.columns else len(result_df),
        "total_annotations": len(result_df),
        "unique_chromosomes": result_df['coord_chr'].nunique() if 'coord_chr' in result_df.columns else 0,
        "annotation_rate": len(result_df) / len(coord_df) if len(coord_df) > 0 else 0.0
    }


class ProgressiveAnnotator:
    """
    Annotate large files in chunks with progress tracking
    """
    
    def __init__(self, chunk_size: int = 100000):
        """
        Initialize progressive annotator
        
        Args:
            chunk_size: Number of rows to process at once
        """
        self.chunk_size = chunk_size
    
    def annotate_large_file(
        self,
        coord_file: str,
        annot_df: pd.DataFrame,
        engine: AnnotationEngine,
        progress_callback: Optional[callable] = None
    ) -> pd.DataFrame:
        """
        Annotate a large coordinate file in chunks
        
        Args:
            coord_file: Path to coordinate file
            annot_df: Annotation DataFrame
            engine: AnnotationEngine instance
            progress_callback: Function to call with progress (0.0 to 1.0)
            
        Returns:
            Complete annotated DataFrame
        """
        results = []
        
        # Read file in chunks
        chunks = pd.read_csv(coord_file, sep='\t', chunksize=self.chunk_size)
        
        total_chunks = sum(1 for _ in pd.read_csv(coord_file, sep='\t', chunksize=self.chunk_size))
        
        for i, chunk in enumerate(chunks):
            # Annotate chunk
            result = engine.intersect(chunk, annot_df)
            results.append(result)
            
            # Report progress
            if progress_callback:
                progress = (i + 1) / total_chunks
                progress_callback(progress)
        
        # Combine results
        return pd.concat(results, ignore_index=True)
