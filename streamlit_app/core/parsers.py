"""
File format parsers for genomic files

Supports:
- Standard formats: BED, GFF, GTF, VCF
- Custom formats: BioMart, UCSC Table Browser, CSV/TSV
- Auto-detection of file format
"""

import pandas as pd
import pysam
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import re


class FormatDetector:
    """Auto-detect file format based on extension and content"""
    
    @staticmethod
    def detect(filepath: str) -> str:
        """
        Detect file format
        
        Args:
            filepath: Path to file
            
        Returns:
            Detected format: 'bed', 'gff', 'gtf', 'vcf', 'custom'
        """
        path = Path(filepath)
        ext = path.suffix.lower().lstrip(".")
        
        # Check extension first
        if ext in ["bed"]:
            return "bed"
        elif ext in ["gff", "gff3"]:
            return "gff"
        elif ext in ["gtf"]:
            return "gtf"
        elif ext in ["vcf"]:
            return "vcf"
        
        # Check content for ambiguous extensions
        if ext in ["txt", "tsv", "csv", ""]:
            return FormatDetector._detect_from_content(filepath)
        
        return "custom"
    
    @staticmethod
    def _detect_from_content(filepath: str) -> str:
        """Detect format from file content"""
        try:
            with open(filepath, 'r') as f:
                # Read first non-comment line
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    fields = line.split('\t')
                    
                    # BED: 3-12 columns, chr/start/end
                    if len(fields) >= 3:
                        if fields[1].isdigit() and fields[2].isdigit():
                            return "bed"
                    
                    # GFF/GTF: 9 columns with specific structure
                    if len(fields) == 9:
                        if fields[2] in ['gene', 'transcript', 'exon', 'CDS']:
                            if 'gene_id' in fields[8]:
                                return "gtf"
                            return "gff"
                    
                    break
        except Exception:
            pass
        
        return "custom"


class BEDParser:
    """Parser for BED format files"""
    
    @staticmethod
    def parse(filepath: str, use_polars_bio: bool = False, **kwargs) -> pd.DataFrame:
        """
        Parse BED file (BED3, BED6, or BED12)
        
        Args:
            filepath: Path to BED file
            
        Returns:
            DataFrame with columns: chr, start, end, [name, score, strand, ...]
        """
        if use_polars_bio:
            try:
                import polars_bio as pb
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("Polars-bio parsing timed out")
                
                # Set 5 second timeout
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(5)
                
                try:
                    lf = pb.scan_bed(filepath)
                    df = lf.collect().to_pandas()
                    signal.alarm(0)  # Cancel alarm
                    return df
                except (TimeoutError, Exception) as e:
                    signal.alarm(0)  # Cancel alarm
                    # Fallback to pandas parser
                    pass
            except Exception:
                pass
        # Fallback to standard parser
        if True:
            # BED files have no header
            df = pd.read_csv(
                filepath,
                sep='\t',
                header=None,
                comment='#',
                **kwargs
            )
            # Assign column names based on number of columns
            ncols = len(df.columns)
            if ncols >= 3:
                df.columns = ['chr', 'start', 'end'] + [f'col{i}' for i in range(4, ncols + 1)]
            if ncols >= 4:
                df.rename(columns={'col4': 'name'}, inplace=True)
            if ncols >= 5:
                df.rename(columns={'col5': 'score'}, inplace=True)
            if ncols >= 6:
                df.rename(columns={'col6': 'strand'}, inplace=True)
            return df
    
    @staticmethod
    def validate(df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
        """
        Validate BED format
        
        Returns:
            (is_valid, error_message)
        """
        required_cols = ['chr', 'start', 'end']
        
        for col in required_cols:
            if col not in df.columns:
                return False, f"Missing required column: {col}"
        
        # Check data types
        if not pd.api.types.is_numeric_dtype(df['start']):
            return False, "'start' column must be numeric"
        
        if not pd.api.types.is_numeric_dtype(df['end']):
            return False, "'end' column must be numeric"
        
        # Check start < end
        if (df['start'] >= df['end']).any():
            return False, "Some intervals have start >= end"
        
        return True, None


class GFFParser:
    """Parser for GFF/GTF format files"""
    
    @staticmethod
    def parse(filepath: str, feature_types: Optional[List[str]] = None, use_polars_bio: bool = False, **kwargs) -> pd.DataFrame:
        """
        Parse GFF/GTF file
        
        Args:
            filepath: Path to GFF/GTF file
            feature_types: List of feature types to extract (e.g., ['gene', 'exon'])
                          If None, extract all features
            
        Returns:
            DataFrame with genomic features
        """
        if use_polars_bio:
            try:
                import polars_bio as pb
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("Polars-bio parsing timed out")
                
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(5)
                
                try:
                    lf = pb.scan_gff(filepath)
                    df = lf.collect().to_pandas()
                    signal.alarm(0)
                    if feature_types:
                        df = df[df['feature'].isin(feature_types)]
                    return df
                except (TimeoutError, Exception) as e:
                    signal.alarm(0)
                    pass
            except Exception:
                pass
        # Fallback to standard parser
        if True:
            # Read GFF/GTF (9 standard columns)
            df = pd.read_csv(
                filepath,
                sep='\t',
                header=None,
                comment='#',
                names=['chr', 'source', 'feature', 'start', 'end', 'score', 'strand', 'frame', 'attributes'],
                **kwargs
            )
            if feature_types:
                df = df[df['feature'].isin(feature_types)]
            df = GFFParser._parse_attributes(df)
            return df
    
    @staticmethod
    def _parse_attributes(df: pd.DataFrame) -> pd.DataFrame:
        """Parse the attributes column into separate columns"""
        df = df.copy()
        
        # Extract common attributes (including GFF3 Name and ID)
        common_attrs = ['ID', 'Name', 'gene_id', 'gene_name', 'transcript_id', 'gene_type', 'gene_biotype', 'Parent']
        
        for attr in common_attrs:
            df[attr] = df['attributes'].apply(
                lambda x: GFFParser._extract_attribute(x, attr)
            )
        
        return df
    
    @staticmethod
    def _extract_attribute(attr_string: str, attr_name: str) -> Optional[str]:
        """Extract a specific attribute from the attributes string"""
        # GTF format: gene_id "ENSG00000123"; gene_name "TP53";
        # GFF3 format: ID=gene:ENSG00000123;Name=TP53
        
        # Try GTF format first
        pattern = rf'{attr_name}\s+"([^"]+)"'
        match = re.search(pattern, attr_string)
        if match:
            return match.group(1)
        
        # Try GFF3 format
        pattern = rf'{attr_name}=([^;]+)'
        match = re.search(pattern, attr_string)
        if match:
            return match.group(1)
        
        return None


class VCFParser:
    """Parser for VCF format files"""
    
    @staticmethod
    def parse(filepath: str, use_polars_bio: bool = False, **kwargs) -> pd.DataFrame:
        """
        Parse VCF file using pysam
        
        Args:
            filepath: Path to VCF file
            
        Returns:
            DataFrame with variant information
        """
        if use_polars_bio:
            try:
                import polars_bio as pb
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("Polars-bio parsing timed out")
                
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(5)
                
                try:
                    lf = pb.scan_vcf(filepath)
                    df = lf.collect().to_pandas()
                    signal.alarm(0)
                    return df
                except (TimeoutError, Exception) as e:
                    signal.alarm(0)
                    pass
            except Exception:
                pass
        # Fallback to standard parser
        if True:
            variants = []
            try:
                vcf = pysam.VariantFile(filepath)
                for record in vcf:
                    variants.append({
                        'chr': record.chrom,
                        'start': record.pos - 1,  # Convert to 0-based
                        'end': record.pos,        # End is exclusive in BED
                        'id': record.id,
                        'ref': record.ref,
                        'alt': ','.join([str(a) for a in record.alts]) if record.alts else '',
                        'qual': record.qual,
                        'filter': ','.join(record.filter.keys()) if record.filter else 'PASS'
                    })
                vcf.close()
            except Exception as e:
                # Fallback to simple parsing if pysam fails
                return VCFParser._simple_parse(filepath)
            return pd.DataFrame(variants)
    
    @staticmethod
    def _simple_parse(filepath: str) -> pd.DataFrame:
        """Simple VCF parser without pysam (fallback)"""
        df = pd.read_csv(
            filepath,
            sep='\t',
            comment='#',
            header=None,
            names=['chr', 'start', 'id', 'ref', 'alt', 'qual', 'filter', 'info', 'format']
        )
        
        # Add end column (same as start for SNPs)
        # Convert to 0-based BED coordinates
        df['end'] = df['start']
        df['start'] = df['start'] - 1
        
        return df[['chr', 'start', 'end', 'id', 'ref', 'alt', 'qual', 'filter']]


class CustomParser:
    """Parser for custom CSV/TSV files (BioMart, UCSC, etc.)"""
    
    # Known column name patterns
    CHR_PATTERNS = [
        'chr', 'chrom', 'chromosome', 'seqname', 'sequence',
        'chromosome/scaffold name', 'chromosome name'
    ]
    
    START_PATTERNS = [
        'start', 'begin', 'pos', 'position', 'txstart', 'chromstart',
        'gene start', 'transcript start'
    ]
    
    END_PATTERNS = [
        'end', 'stop', 'txend', 'chromend',
        'gene end', 'transcript end'
    ]
    
    @staticmethod
    def parse(
        filepath: str,
        delimiter: Optional[str] = None,
        has_header: bool = True,
        **kwargs
    ) -> pd.DataFrame:
        """
        Parse custom CSV/TSV file
        
        Args:
            filepath: Path to file
            delimiter: Field delimiter (auto-detected if None)
            has_header: Whether file has header row
            
        Returns:
            DataFrame
        """
        # Auto-detect delimiter
        if delimiter is None:
            delimiter = CustomParser._detect_delimiter(filepath)
        
        # Read file
        df = pd.read_csv(
            filepath,
            sep=delimiter,
            header=0 if has_header else None,
            comment='#',
            **kwargs
        )
        
        return df
    
    @staticmethod
    def _detect_delimiter(filepath: str) -> str:
        """Detect delimiter (tab, comma, space)"""
        with open(filepath, 'r') as f:
            # Skip comment lines
            for line in f:
                if not line.startswith('#'):
                    first_line = line
                    break
        
        # Count delimiters
        tab_count = first_line.count('\t')
        comma_count = first_line.count(',')
        
        if tab_count > comma_count:
            return '\t'
        elif comma_count > 0:
            return ','
        else:
            return r'\s+'  # Whitespace
    
    @staticmethod
    def suggest_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
        """
        Suggest which columns correspond to chr, start, end
        
        Args:
            df: DataFrame
            
        Returns:
            Dict with suggested column names: {'chr': 'col1', 'start': 'col2', 'end': 'col3'}
        """
        columns_lower = {col: col.lower() for col in df.columns}
        
        suggestions = {
            'chr': None,
            'start': None,
            'end': None
        }
        
        # Find chromosome column
        for col, col_lower in columns_lower.items():
            for pattern in CustomParser.CHR_PATTERNS:
                if pattern in col_lower:
                    suggestions['chr'] = col
                    break
            if suggestions['chr']:
                break
        
        # Find start column
        for col, col_lower in columns_lower.items():
            for pattern in CustomParser.START_PATTERNS:
                if pattern in col_lower:
                    suggestions['start'] = col
                    break
            if suggestions['start']:
                break
        
        # Find end column
        for col, col_lower in columns_lower.items():
            for pattern in CustomParser.END_PATTERNS:
                if pattern in col_lower:
                    suggestions['end'] = col
                    break
            if suggestions['end']:
                break
        
        return suggestions
    
    @staticmethod
    def map_columns(
        df: pd.DataFrame,
        chr_col: str,
        start_col: str,
        end_col: Optional[str] = None,
        additional_cols: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Map custom columns to standard format
        
        Args:
            df: Input DataFrame
            chr_col: Chromosome column name
            start_col: Start column name
            end_col: End column name (optional for SNPs)
            additional_cols: Additional columns to keep
            
        Returns:
            DataFrame with standardized columns
        """
        # Create column mapping
        rename_map = {
            chr_col: 'chr',
            start_col: 'start'
        }
        
        if end_col:
            rename_map[end_col] = 'end'
        
        # Select columns
        cols_to_keep = [chr_col, start_col]
        if end_col:
            cols_to_keep.append(end_col)
        if additional_cols:
            cols_to_keep.extend(additional_cols)
        
        df = df[cols_to_keep].copy()
        df.rename(columns=rename_map, inplace=True)
        
        return df
