"""
File format parsers for genomic files

Supports:
- Standard formats: BED, GFF, GTF, VCF
- Custom formats: BioMart, UCSC Table Browser, CSV/TSV
- Auto-detection of file format
"""

import pandas as pd
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import re

from .schema import MalformedFileError


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
    """Parser for BED format files (BED3..BED12+)"""
    
    #: Optional BED column names after the required chrom/start/end.
    #: Deeper fields (7+) keep generic names.
    _OPTIONAL_COLUMNS = {4: 'name', 5: 'score', 6: 'strand'}
    
    @staticmethod
    def parse(filepath: str) -> pd.DataFrame:
        """
        Parse BED file (BED3, BED6, or BED12+)
        
        BED is 0-based half-open [start, end), so the source-level output
        is already in the canonical coordinate convention; normalization is
        a no-op for BED coordinates.
        
        Variable-width rows are supported: optional fields present on some
        rows are missing (NA) on rows that lack them. Structurally invalid
        rows (fewer than 3 fields, or non-integer coordinates) raise
        MalformedFileError with the offending physical line number —
        records are never silently dropped.
        
        Args:
            filepath: Path to BED file
            
        Returns:
            DataFrame with columns: chr, start, end, [name, score, strand, ...]
        """
        rows: List[Dict] = []
        max_cols = 3
        
        with open(filepath, 'r') as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.rstrip('\n')
                if not line.strip() or line.startswith('#'):
                    continue
                fields = line.split('\t')
                if len(fields) < 3:
                    raise MalformedFileError(
                        f'line {line_number}: expected at least 3 '
                        f'tab-separated fields, got {len(fields)}'
                    )
                try:
                    start = int(fields[1])
                    end = int(fields[2])
                except ValueError:
                    raise MalformedFileError(
                        f'line {line_number}: start/end must be integers, '
                        f'got {fields[1]!r}/{fields[2]!r}'
                    )
                row = {'chr': fields[0], 'start': start, 'end': end}
                for index, value in enumerate(fields[3:], start=4):
                    row[BEDParser._OPTIONAL_COLUMNS.get(index, f'col{index}')] = value
                max_cols = max(max_cols, len(fields))
                rows.append(row)
        
        if not rows:
            return pd.DataFrame(columns=['chr', 'start', 'end'])
        
        df = pd.DataFrame(rows)
        ordered = ['chr', 'start', 'end'] + [
            BEDParser._OPTIONAL_COLUMNS.get(index, f'col{index}')
            for index in range(4, max_cols + 1)
            if BEDParser._OPTIONAL_COLUMNS.get(index, f'col{index}') in df.columns
        ]
        return df[ordered]
    
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
    def parse(
        filepath: str,
        feature_types: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Parse GFF/GTF file
        
        GFF is 1-based inclusive [start, end]; conversion to the canonical
        0-based half-open model is applied later by normalization, not here.
        
        Args:
            filepath: Path to GFF/GTF file
            feature_types: List of feature types to extract (e.g., ['gene', 'exon'])
                          If None, extract all features
            
        Returns:
            DataFrame with genomic features
        """
        # Read GFF/GTF (9 standard columns)
        df = pd.read_csv(
            filepath,
            sep='\t',
            header=None,
            comment='#',
            names=['chr', 'source', 'feature', 'start', 'end', 'score', 'strand', 'frame', 'attributes'],
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
    
    _COLUMNS = ['chr', 'start', 'end', 'id', 'ref', 'alt', 'qual', 'filter']
    
    @staticmethod
    def _variant_span(ref, end_info, pos: int) -> int:
        """
        Number of bases occupied by a variant at 1-based ``pos``.
        
        Per the VCF specification the reference interval occupied by a
        variant is ``[POS, POS + max(1, len(REF)) - 1]``; when ``INFO/END``
        is present the occupied interval is ``[POS, END]`` (both ends
        1-based inclusive).
        """
        if end_info is not None:
            span = int(end_info) - pos + 1
            if span < 1:
                raise MalformedFileError(
                    f'VCF variant at POS {pos}: INFO/END {end_info} precedes POS'
                )
            return span
        ref_len = len(ref) if isinstance(ref, str) else 0
        return max(1, ref_len)
    
    @staticmethod
    def _info_end(info_field) -> Optional[int]:
        """Extract INFO/END from a raw INFO field, or None when absent."""
        match = re.search(r'(?:^|;)END=(\d+)', info_field or '')
        return int(match.group(1)) if match else None
    
    @classmethod
    def parse(cls, filepath: str) -> pd.DataFrame:
        """
        Parse VCF file into a source-level 1-based inclusive table.
        
        Each variant becomes the interval occupied by its reference
        sequence (see ``_variant_span``): ``start = POS`` and
        ``end = POS + span - 1``, both 1-based inclusive. Normalization
        later converts that span to the canonical 0-based half-open
        model. Task 2 limitation: the span is derived from INFO/END or
        REF length only; broader structural-variant interpretation is not
        performed.
        
        Parsing is explicit and line-based: the VCF specification fixes
        the first eight tab-separated fields (CHROM POS ID REF ALT QUAL
        FILTER INFO) and tabs inside INFO values are escaped, so plain
        text parsing is complete for the fields this app needs. This
        avoids version-dependent behavior of external VCF libraries
        (e.g. pysam builds that do not expose INFO/END through their
        record API). Structurally invalid data lines raise
        MalformedFileError with the offending physical line number —
        records are never silently dropped.
        
        Args:
            filepath: Path to VCF file
            
        Returns:
            DataFrame with columns: chr, start, end, id, ref, alt, qual, filter
        """
        rows: List[Dict] = []
        
        with open(filepath, 'r') as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.rstrip('\n')
                if not line.strip() or line.startswith('#'):
                    continue
                fields = line.split('\t')
                if len(fields) < 8:
                    raise MalformedFileError(
                        f'line {line_number}: expected at least 8 tab-separated '
                        f'fields (CHROM POS ID REF ALT QUAL FILTER INFO), '
                        f'got {len(fields)}'
                    )
                chrom, pos_s, vid, ref, alt, qual, filt, info = fields[:8]
                try:
                    pos = int(pos_s)
                except ValueError:
                    raise MalformedFileError(
                        f'line {line_number}: POS must be an integer, got {pos_s!r}'
                    )
                span = cls._variant_span(ref, cls._info_end(info), pos)
                rows.append({
                    'chr': chrom,
                    'start': pos,
                    'end': pos + span - 1,
                    'id': None if vid == '.' else vid,
                    'ref': ref,
                    'alt': alt,
                    'qual': None if qual == '.' else float(qual),
                    'filter': 'PASS' if filt == '.' else filt,
                })
        
        if not rows:
            return pd.DataFrame(columns=cls._COLUMNS)
        return pd.DataFrame(rows, columns=cls._COLUMNS)


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
