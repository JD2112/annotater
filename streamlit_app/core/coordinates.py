"""
Coordinate system handling and conversion

Handles conversion between 0-based and 1-based coordinate systems:
- 0-based (BED, BAM): Half-open interval [start, end)
- 1-based (GFF, GTF, VCF, SAM): Closed interval [start, end]
"""

from typing import Tuple, Optional, Literal
import pandas as pd


class CoordinateConverter:
    """
    Handle coordinate system conversions between 0-based and 1-based
    """
    
    # Format to coordinate system mapping
    FORMAT_SYSTEMS = {
        "bed": "0-based",
        "bam": "0-based",
        "gff": "1-based",
        "gtf": "1-based",
        "gff3": "1-based",
        "vcf": "1-based",
        "sam": "1-based",
    }
    
    @staticmethod
    def convert(
        start: int,
        end: Optional[int] = None,
        from_system: Literal["0-based", "1-based"] = "0-based",
        to_system: Literal["0-based", "1-based"] = "1-based"
    ) -> Tuple[int, Optional[int]]:
        """
        Convert coordinates between systems
        
        Args:
            start: Start position
            end: End position (optional)
            from_system: Source coordinate system
            to_system: Target coordinate system
            
        Returns:
            Tuple of (converted_start, converted_end)
            
        Examples:
            >>> # 0-based [100, 200) -> 1-based [101, 200]
            >>> convert(100, 200, "0-based", "1-based")
            (101, 200)
            
            >>> # 1-based [101, 200] -> 0-based [100, 200)
            >>> convert(101, 200, "1-based", "0-based")
            (100, 200)
        """
        if from_system == to_system:
            return start, end
        
        if from_system == "0-based" and to_system == "1-based":
            # 0-based to 1-based: add 1 to start
            return start + 1, end
        elif from_system == "1-based" and to_system == "0-based":
            # 1-based to 0-based: subtract 1 from start
            return start - 1, end
        
        return start, end
    
    @classmethod
    def detect_system(cls, file_format: str) -> str:
        """
        Auto-detect coordinate system based on file format
        
        Args:
            file_format: File format (e.g., 'bed', 'gff', 'vcf')
            
        Returns:
            Coordinate system: '0-based' or '1-based'
        """
        file_format = file_format.lower().replace(".", "")
        return cls.FORMAT_SYSTEMS.get(file_format, "1-based")  # Default to 1-based
    
    @classmethod
    def convert_dataframe(
        cls,
        df: pd.DataFrame,
        from_system: str,
        to_system: str,
        start_col: str = "start",
        end_col: str = "end"
    ) -> pd.DataFrame:
        """
        Convert all coordinates in a DataFrame
        
        Args:
            df: DataFrame with start and end columns
            from_system: Source coordinate system
            to_system: Target coordinate system
            start_col: Name of start column
            end_col: Name of end column
            
        Returns:
            DataFrame with converted coordinates
        """
        if from_system == to_system:
            return df
        
        df = df.copy()
        
        if start_col in df.columns:
            if from_system == "0-based" and to_system == "1-based":
                df[start_col] = df[start_col] + 1
            elif from_system == "1-based" and to_system == "0-based":
                df[start_col] = df[start_col] - 1
        
        return df


class CoordinateNormalizer:
    """
    Handle both single position (SNPs) and intervals (ranges)
    """
    
    @staticmethod
    def normalize(
        chr: str,
        start: int,
        end: Optional[int] = None,
        is_snp: bool = False,
        coordinate_system: str = "0-based"
    ) -> Tuple[str, int, int]:
        """
        Normalize coordinates to interval format
        
        Single positions (SNPs) are converted to 1bp intervals:
        - For 0-based: position P → [P, P+1)
        - For 1-based: position P → [P, P]
        
        Args:
            chr: Chromosome identifier
            start: Start position (or single position for SNPs)
            end: End position (None for SNPs)
            is_snp: Whether this is a single position
            coordinate_system: '0-based' or '1-based'
            
        Returns:
            Tuple of (chr, start, end) as interval
            
        Examples:
            >>> # SNP at position 100 (0-based)
            >>> normalize('chr1', 100, None, is_snp=True, coordinate_system='0-based')
            ('chr1', 100, 101)
            
            >>> # SNP at position 101 (1-based)
            >>> normalize('chr1', 101, None, is_snp=True, coordinate_system='1-based')
            ('chr1', 101, 101)
            
            >>> # Interval (already normalized)
            >>> normalize('chr1', 100, 200, is_snp=False)
            ('chr1', 100, 200)
        """
        if end is None or is_snp:
            # Single position - convert to interval
            if coordinate_system == "0-based":
                # 0-based: position P → [P, P+1)
                return chr, start, start + 1
            else:
                # 1-based: position P → [P, P]
                return chr, start, start
        
        # Already an interval
        return chr, start, end
    
    @staticmethod
    def is_single_position(start: int, end: Optional[int], coordinate_system: str = "0-based") -> bool:
        """
        Check if interval represents a single position
        
        Args:
            start: Start position
            end: End position
            coordinate_system: '0-based' or '1-based'
            
        Returns:
            True if single position, False otherwise
        """
        if end is None:
            return True
        
        if coordinate_system == "0-based":
            # In 0-based, single position: end = start + 1
            return end == start + 1
        else:
            # In 1-based, single position: end = start
            return end == start
    
    @staticmethod
    def normalize_dataframe(
        df: pd.DataFrame,
        chr_col: str = "chr",
        start_col: str = "start",
        end_col: Optional[str] = "end",
        coordinate_system: str = "0-based"
    ) -> pd.DataFrame:
        """
        Normalize all coordinates in a DataFrame
        
        Args:
            df: Input DataFrame
            chr_col: Chromosome column name
            start_col: Start column name
            end_col: End column name (None if single positions)
            coordinate_system: '0-based' or '1-based'
            
        Returns:
            DataFrame with normalized coordinates
        """
        df = df.copy()
        
        if end_col is None or end_col not in df.columns:
            # All single positions - add end column
            if coordinate_system == "0-based":
                df["end"] = df[start_col] + 1
            else:
                df["end"] = df[start_col]
        else:
            # Check for missing end values
            mask = df[end_col].isna()
            if mask.any():
                if coordinate_system == "0-based":
                    df.loc[mask, end_col] = df.loc[mask, start_col] + 1
                else:
                    df.loc[mask, end_col] = df.loc[mask, start_col]
        
        return df
