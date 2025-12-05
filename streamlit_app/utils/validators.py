"""Input validation utilities"""

import pandas as pd
from pathlib import Path
from typing import Tuple, Optional, List
from config import Settings


class FileValidator:
    """Validate uploaded files"""
    
    @staticmethod
    def validate_file_size(file, max_size_bytes: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if file size is within limits
        
        Args:
            file: Uploaded file object
            max_size_bytes: Maximum size in bytes (uses Settings default if None)
            
        Returns:
            (is_valid, error_message)
        """
        if max_size_bytes is None:
            max_size_bytes = Settings.get_max_file_size_bytes()
        
        file_size = file.size if hasattr(file, 'size') else len(file.getvalue())
        
        if file_size > max_size_bytes:
            max_mb = max_size_bytes / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            return False, f"File too large: {actual_mb:.1f}MB (max: {max_mb:.0f}MB)"
        
        return True, None
    
    @staticmethod
    def validate_file_extension(
        filename: str,
        allowed_extensions: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if file has allowed extension
        
        Args:
            filename: Name of file
            allowed_extensions: List of allowed extensions (with or without dot)
            
        Returns:
            (is_valid, error_message)
        """
        ext = Path(filename).suffix.lower()
        
        # Normalize extensions
        allowed = [e if e.startswith('.') else f'.{e}' for e in allowed_extensions]
        
        if ext not in allowed:
            return False, f"Invalid file type '{ext}'. Allowed: {', '.join(allowed)}"
        
        return True, None


class DataValidator:
    """Validate DataFrame contents"""
    
    @staticmethod
    def validate_coordinates(df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
        """
        Validate coordinate DataFrame
        
        Checks:
        - Required columns exist
        - Start and end are numeric
        - Start < end
        - No negative coordinates
        
        Returns:
            (is_valid, error_message)
        """
        # Check required columns
        required = ['chr', 'start', 'end']
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            return False, f"Missing required columns: {', '.join(missing)}"
        
        # Check numeric types
        if not pd.api.types.is_numeric_dtype(df['start']):
            return False, "'start' column must be numeric"
        
        if not pd.api.types.is_numeric_dtype(df['end']):
            return False, "'end' column must be numeric"
        
        # Check for negative coordinates
        if (df['start'] < 0).any():
            return False, "Negative coordinates found in 'start' column"
        
        if (df['end'] < 0).any():
            return False, "Negative coordinates found in 'end' column"
        
        # Check start < end
        invalid_intervals = df[df['start'] >= df['end']]
        if len(invalid_intervals) > 0:
            return False, f"Found {len(invalid_intervals)} intervals with start >= end"
        
        return True, None
    
    @staticmethod
    def validate_chromosomes(df: pd.DataFrame, chr_col: str = 'chr') -> Tuple[bool, Optional[str]]:
        """
        Validate chromosome identifiers
        
        Returns:
            (is_valid, error_message)
        """
        if chr_col not in df.columns:
            return False, f"Chromosome column '{chr_col}' not found"
        
        # Check for empty values
        if df[chr_col].isna().any():
            return False, "Found empty chromosome identifiers"
        
        return True, None
    
    @staticmethod
    def get_data_summary(df: pd.DataFrame) -> dict:
        """
        Generate summary statistics for a DataFrame
        
        Returns:
            Dictionary with summary information
        """
        summary = {
            "rows": len(df),
            "columns": len(df.columns),
            "memory_mb": df.memory_usage(deep=True).sum() / (1024 * 1024),
        }
        
        if 'chr' in df.columns:
            summary["chromosomes"] = df['chr'].nunique()
            summary["chromosome_list"] = sorted(df['chr'].unique().tolist())
        
        if all(col in df.columns for col in ['start', 'end']):
            summary["total_span"] = (df['end'] - df['start']).sum()
            summary["median_length"] = (df['end'] - df['start']).median()
        
        return summary
