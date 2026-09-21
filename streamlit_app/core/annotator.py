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


class PolarsBioEngine(AnnotationEngine):
    """
    High-performance engine using Polars and Polars-Bio (Rust backend)
    """
    
    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        # import streamlit as st
        # st.info(f"[PolarsBioEngine] Input coord_df shape: {coord_df.shape}, annot_df shape: {annot_df.shape}")
        # st.write("coord_df head:", coord_df.head())
        # st.write("annot_df head:", coord_df.head())

        # Convert pandas to polars
        # Ensure standard column names and types
        q_coord = self._prepare_polars(coord_df, prefix="coord")
        q_annot = self._prepare_polars(annot_df, prefix="annot")

        # st.write("q_coord head:", q_coord.head())
        # st.write("q_annot head:", q_annot.head())

        # Perform intersection based on mode
        if self.mode == "overlap":
            result = self._join_overlap(q_coord, q_annot, how)
        elif self.mode == "closest":
            result = self._find_nearest(q_coord, q_annot)
        elif self.mode in ["contains", "within"]:
            # Polars-bio doesn't have direct 'contains/within' verify flags yet in high level API
            # typically, use overlap + filter
            result = self._join_overlap(q_coord, q_annot, how)
            result = self._filter_fraction(result, mode=self.mode)
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

        # st.info(f"[PolarsBioEngine] Overlap result shape: {result.shape if hasattr(result, 'shape') else 'N/A'})
        # if hasattr(result, 'head'):
        #     st.write("result head:", result.head())

        # Post-process and return pandas
        return self._post_process(result)

    def _prepare_polars(self, df: pd.DataFrame, prefix: str) -> pl.DataFrame:
        """Convert to polars and enforce schema"""
        # Ensure core columns are present and correct type
        pdf = pl.from_pandas(df)
        
        # Rename for disambiguation
        # We need specific names for polars-bio functions usually, 
        # but let's keep it simple: chr, start, end are needed for the join keys
        # We will rename AFTER the join usually, or before?
        # polars-bio 'join_overlap' takes 2 frames and on/start/end column names.
        
        # Cast to proper types
        pdf = pdf.with_columns([
            pl.col('chr').cast(pl.Utf8),
            pl.col('start').cast(pl.Int64),
            pl.col('end').cast(pl.Int64)
        ])
        
        return pdf

    def _join_overlap(self, coord: pl.DataFrame, annot: pl.DataFrame, how: str) -> pl.DataFrame:
        """Wrapper for polars-bio overlap"""
        # polars-bio uses pb.overlap(df1, df2, output_type="polars.DataFrame")
        # It returns overlapping pairs with columns from both DataFrames

        # Row id lets us restore non-overlapping coordinates when how='left'
        coord = coord.with_row_index("pb_row_id")

        try:
            # Convert polars DataFrames to pandas for pb.overlap
            coord_pd = coord.to_pandas()
            annot_pd = annot.to_pandas()
            # Rename 'chr' to 'chrom' for polars-bio compatibility
            if 'chr' in coord_pd.columns:
                coord_pd = coord_pd.rename(columns={'chr': 'chrom'})
            if 'chr' in annot_pd.columns:
                annot_pd = annot_pd.rename(columns={'chr': 'chrom'})
            # Call pb.overlap with pandas DataFrames
            res_pd = pb.overlap(coord_pd, annot_pd, output_type="pandas.DataFrame")
            # Convert back to polars
            res = pl.from_pandas(res_pd)
        except Exception as e:
            # Log the error and return empty
            logger.error("[PolarsBio] pb.overlap failed: %s: %s", type(e).__name__, e, exc_info=True)
            return pl.DataFrame()

        if how == "left":
            # Restore coordinates without overlaps by left-joining the overlap
            # result back onto all coordinates via the row id.
            id_cols = [c for c in res.columns if "pb_row_id" in c]
            if id_cols:
                res = res.rename({id_cols[0]: "pb_row_id"})
                res = res.with_columns(pl.lit(True).alias("pb_has_overlap"))
                res = coord.join(res, on="pb_row_id", how="left")
                res = res.with_columns(
                    pl.col("pb_has_overlap").fill_null(False).alias("has_overlap")
                )
                res = res.drop(["pb_row_id", "pb_has_overlap"])
            else:
                # pb.overlap dropped the row id; degrade to inner join
                logger.warning("[PolarsBio] pb.overlap result has no row id; 'left' degraded to inner join")

        return res

    def _find_nearest(self, coord: pl.DataFrame, annot: pl.DataFrame) -> pl.DataFrame:
        """Wrapper for polars-bio nearest"""
        try:
            logger.debug("[PolarsBio] pb.nearest: coord %s, annot %s", coord.shape, annot.shape)
            # Convert to pandas for pb.nearest
            coord_pd = coord.to_pandas()
            annot_pd = annot.to_pandas()
            
            # Rename 'chr' to 'chrom' for polars-bio compatibility
            if 'chr' in coord_pd.columns:
                coord_pd = coord_pd.rename(columns={'chr': 'chrom'})
            if 'chr' in annot_pd.columns:
                annot_pd = annot_pd.rename(columns={'chr': 'chrom'})
            
            # Call pb.nearest with pandas DataFrames
            res_pd = pb.nearest(coord_pd, annot_pd, output_type="pandas.DataFrame")
            logger.debug("[PolarsBio] pb.nearest succeeded: %s", res_pd.shape)
            return pl.from_pandas(res_pd)
        except Exception as e:
            logger.error("[PolarsBio] pb.nearest failed: %s: %s", type(e).__name__, e, exc_info=True)
            return pl.DataFrame()

    def _filter_fraction(self, res: pl.DataFrame, mode: str) -> pl.DataFrame:
        # Calculate overlap length and filter based on min_overlap/contains/within
        # For now, return as is (placeholder for advanced logic)
        return res

    def _post_process(self, res: pl.DataFrame) -> pd.DataFrame:
        if res is None or res.is_empty():
            return pd.DataFrame()
            
        # Convert back to pandas
        df = res.to_pandas()
        
        # Rename columns to match Expected Output (coord_..., annot_...)
        # This mapping depends heavily on what polars-bio output look like (suffixes)
        # For this implementation, we will perform a smart rename.
        
        # Identify which columns came from right (annot).
        # Polars usually suffixes right with "_right".
        
        cols = df.columns
        new_names = {}
        
        for c in cols:
            if c == 'has_overlap':
                continue
            if c.endswith("_right"):
                base = c.replace("_right", "")
                new_names[c] = f"annot_{base}"
            elif c in ['chr', 'start', 'end']:
                new_names[c] = f"coord_{c}"
            else:
                # Assume strictly left columns are coord (if not right)
                # This handles extra columns from right that didn't collide?
                # Actually, polars-bio might preserve original names.
                # Use heuristic: if it has 'annot' prefix or is from annot cols...
                new_names[c] = f"coord_{c}"
        
        df = df.rename(columns=new_names)
        
        # Add has_overlap if the engine didn't already compute it
        # (inner joins overlap for every row; left joins carry the flag).
        if 'has_overlap' not in df.columns:
            df['has_overlap'] = True
        
        return df


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
