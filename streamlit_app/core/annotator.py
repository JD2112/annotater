"""
Annotation engine for coordinate intersection

Uses pybedtools for fast, memory-efficient genomic coordinate operations
"""

import pybedtools
import pandas as pd
from typing import Optional, Literal, Dict
from pathlib import Path
import tempfile


class AnnotationEngine:
    """
    High-performance coordinate intersection using bedtools
    """
    
    def __init__(
        self,
        use_strand: bool = False,
        min_overlap: Optional[float] = None,
        mode: Literal["overlap", "contains", "within", "closest"] = "overlap"
    ):
        """
        Initialize annotation engine
        
        Args:
            use_strand: Require same strand for overlaps
            min_overlap: Minimum fraction of overlap (0.0 to 1.0)
            mode: Annotation mode
        """
        self.use_strand = use_strand
        self.min_overlap = min_overlap
        self.mode = mode
    
    def intersect(
        self,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame,
        how: Literal["inner", "left"] = "inner"
    ) -> pd.DataFrame:
        """
        Perform intersection between coordinates and annotations
        
        Args:
            coord_df: DataFrame with chr, start, end columns
            annot_df: Annotation DataFrame with chr, start, end columns
            how: 'inner' (only overlaps), 'left' (all coords, with/without overlaps)
            
        Returns:
            Annotated DataFrame
        """
        # Validate required columns
        for df, name in [(coord_df, "coordinate"), (annot_df, "annotation")]:
            if not all(col in df.columns for col in ['chr', 'start', 'end']):
                raise ValueError(f"{name} DataFrame must have 'chr', 'start', 'end' columns")
        
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
            # Cleanup temporary files
            coord_bed.delete_temporary_files()
            annot_bed.delete_temporary_files()
        
        return result_df
    
    def _df_to_bedtool(self, df: pd.DataFrame, prefix: str = "temp") -> pybedtools.BedTool:
        """Convert DataFrame to BedTool object"""
        # Ensure proper column order and types
        bed_df = df[['chr', 'start', 'end']].copy()
        bed_df['start'] = bed_df['start'].astype(int)
        bed_df['end'] = bed_df['end'].astype(int)
        
        # Add additional columns if present
        extra_cols = [col for col in df.columns if col not in ['chr', 'start', 'end']]
        for col in extra_cols[:3]:  # BED format supports up to 12 columns, keep first 3 extra
            bed_df[col] = df[col].astype(str)
        
        # Create BedTool
        return pybedtools.BedTool.from_dataframe(bed_df)
    
    def _intersect_overlap(
        self,
        coord_bed: pybedtools.BedTool,
        annot_bed: pybedtools.BedTool,
        how: str
    ) -> pybedtools.BedTool:
        """Find overlapping annotations"""
        kwargs = {
            "wa": True,  # Write original coord entry
            "wb": True,  # Write original annotation entry
            "s": self.use_strand,  # Require same strand
        }
        
        if self.min_overlap:
            kwargs["f"] = self.min_overlap
        
        if how == "left":
            kwargs["loj"] = True  # Left outer join
        
        return coord_bed.intersect(annot_bed, **kwargs)
    
    def _intersect_contains(
        self,
        coord_bed: pybedtools.BedTool,
        annot_bed: pybedtools.BedTool
    ) -> pybedtools.BedTool:
        """Find annotations that completely contain coordinates"""
        return coord_bed.intersect(
            annot_bed,
            wa=True,
            wb=True,
            f=1.0,  # Coordinate must be 100% within annotation
            s=self.use_strand
        )
    
    def _intersect_within(
        self,
        coord_bed: pybedtools.BedTool,
        annot_bed: pybedtools.BedTool
    ) -> pybedtools.BedTool:
        """Find annotations completely within coordinates"""
        return coord_bed.intersect(
            annot_bed,
            wa=True,
            wb=True,
            F=1.0,  # Annotation must be 100% within coordinate
            s=self.use_strand
        )
    
    def _find_closest(
        self,
        coord_bed: pybedtools.BedTool,
        annot_bed: pybedtools.BedTool
    ) -> pybedtools.BedTool:
        """Find nearest annotation for each coordinate"""
        return coord_bed.closest(
            annot_bed,
            d=True,  # Report distance
            t="first",  # Report first match (closest)
            s=self.use_strand
        )
    
    def _bedtool_to_df(
        self,
        bedtool: pybedtools.BedTool,
        coord_df: pd.DataFrame,
        annot_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Convert BedTool result back to DataFrame with proper column names
        """
        # Convert to DataFrame
        try:
            result_df = bedtool.to_dataframe()
        except Exception:
            # If conversion fails, return empty DataFrame
            return pd.DataFrame()
        
        if result_df.empty:
            return result_df
        
        # Determine number of columns from each source
        coord_cols = min(len(coord_df.columns), 6)  # BED uses max 6 standard cols
        annot_cols = min(len(annot_df.columns), 6)
        
        # Rename columns
        col_names = []
        
        # Coordinate columns
        col_names.extend([f"coord_{col}" for col in coord_df.columns[:coord_cols]])
        
        # Annotation columns
        col_names.extend([f"annot_{col}" for col in annot_df.columns[:annot_cols]])
        
        # Distance column (for closest mode)
        if self.mode == "closest" and len(result_df.columns) > coord_cols + annot_cols:
            col_names.append("distance")
        
        # Assign column names
        result_df.columns = col_names[:len(result_df.columns)]
        
        return result_df
    
    def get_summary_stats(self, result_df: pd.DataFrame, coord_df: pd.DataFrame) -> Dict:
        """
        Generate summary statistics about annotation results
        
        Args:
            result_df: Result DataFrame from intersect()
            coord_df: Original coordinate DataFrame
            
        Returns:
            Dictionary with summary statistics
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
