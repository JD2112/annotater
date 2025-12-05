"""
Chromosome ID standardization and mapping

Handles conversion between different chromosome naming conventions:
- UCSC: chr1, chr2, ..., chrX, chrY, chrM
- Ensembl: 1, 2, ..., X, Y, MT
- NCBI: NC_000001.11, etc.
"""

import re
from typing import List, Dict, Optional, Tuple
import pandas as pd


class ChromosomeMapper:
    """
    Bidirectional mapping between chromosome naming conventions
    """
    
    # Comprehensive chromosome mappings
    MAPPINGS = {
        "ucsc_to_ensembl": {
            "chr1": "1", "chr2": "2", "chr3": "3", "chr4": "4", "chr5": "5",
            "chr6": "6", "chr7": "7", "chr8": "8", "chr9": "9", "chr10": "10",
            "chr11": "11", "chr12": "12", "chr13": "13", "chr14": "14", "chr15": "15",
            "chr16": "16", "chr17": "17", "chr18": "18", "chr19": "19", "chr20": "20",
            "chr21": "21", "chr22": "22", "chrX": "X", "chrY": "Y", "chrM": "MT"
        },
        "ensembl_to_ucsc": {
            "1": "chr1", "2": "chr2", "3": "chr3", "4": "chr4", "5": "chr5",
            "6": "chr6", "7": "chr7", "8": "chr8", "9": "chr9", "10": "chr10",
            "11": "chr11", "12": "chr12", "13": "chr13", "14": "chr14", "15": "chr15",
            "16": "chr16", "17": "chr17", "18": "chr18", "19": "chr19", "20": "chr20",
            "21": "chr21", "22": "chr22", "X": "chrX", "Y": "chrY", "MT": "chrM"
        }
    }
    
    # Regex patterns for style detection
    PATTERNS = {
        "ucsc": re.compile(r"^chr[0-9XYM]+$", re.IGNORECASE),
        "ensembl": re.compile(r"^[0-9]+$|^[XYM]$|^MT$", re.IGNORECASE),
        "ncbi": re.compile(r"^NC_[0-9]+\.[0-9]+$")
    }
    
    def detect_style(self, chromosomes: List[str]) -> Optional[str]:
        """
        Detect chromosome naming style from a list of chromosome IDs
        
        Args:
            chromosomes: List of chromosome identifiers
            
        Returns:
            Detected style: 'ucsc', 'ensembl', 'ncbi', or None
        """
        if not chromosomes:
            return None
        
        # Count matches for each style
        style_counts = {style: 0 for style in self.PATTERNS.keys()}
        
        for chrom in chromosomes[:50]:  # Sample first 50 chromosomes
            chrom = str(chrom).strip()
            for style, pattern in self.PATTERNS.items():
                if pattern.match(chrom):
                    style_counts[style] += 1
                    break
        
        # Return style with most matches
        if max(style_counts.values()) > 0:
            return max(style_counts, key=style_counts.get)
        
        return None
    
    def convert(
        self,
        chrom: str,
        from_style: str,
        to_style: str
    ) -> str:
        """
        Convert a single chromosome ID from one style to another
        
        Args:
            chrom: Chromosome identifier
            from_style: Source style ('ucsc', 'ensembl')
            to_style: Target style ('ucsc', 'ensembl')
            
        Returns:
            Converted chromosome ID, or original if no mapping exists
        """
        if from_style == to_style:
            return chrom
        
        mapping_key = f"{from_style}_to_{to_style}"
        
        if mapping_key in self.MAPPINGS:
            return self.MAPPINGS[mapping_key].get(chrom, chrom)
        
        # If no direct mapping, try to infer
        if from_style == "ucsc" and to_style == "ensembl":
            # Remove 'chr' prefix
            return chrom.replace("chr", "").replace("M", "MT")
        elif from_style == "ensembl" and to_style == "ucsc":
            # Add 'chr' prefix
            chrom = chrom.replace("MT", "M")
            return f"chr{chrom}" if not chrom.startswith("chr") else chrom
        
        return chrom
    
    def standardize_dataframe(
        self,
        df: pd.DataFrame,
        chr_column: str = "chr",
        target_style: str = "ucsc"
    ) -> Tuple[pd.DataFrame, str, str]:
        """
        Standardize all chromosome IDs in a DataFrame
        
        Args:
            df: DataFrame with chromosome column
            chr_column: Name of chromosome column
            target_style: Target naming style
            
        Returns:
            Tuple of (standardized DataFrame, detected source style, target style)
        """
        if chr_column not in df.columns:
            raise ValueError(f"Column '{chr_column}' not found in DataFrame")
        
        # Detect current style
        chromosomes = df[chr_column].unique().tolist()
        source_style = self.detect_style(chromosomes)
        
        if source_style is None:
            # Cannot detect style, return as-is
            return df, "unknown", target_style
        
        if source_style == target_style:
            # Already in target style
            return df, source_style, target_style
        
        # Convert all chromosomes
        df = df.copy()
        df[chr_column] = df[chr_column].apply(
            lambda x: self.convert(str(x), source_style, target_style)
        )
        
        return df, source_style, target_style
    
    def find_mismatches(
        self,
        coord_chromosomes: List[str],
        annot_chromosomes: List[str]
    ) -> Dict[str, any]:
        """
        Find mismatches between coordinate and annotation chromosome IDs
        
        Args:
            coord_chromosomes: List of chromosomes from coordinate file
            annot_chromosomes: List of chromosomes from annotation file
            
        Returns:
            Dictionary with mismatch information
        """
        coord_style = self.detect_style(coord_chromosomes)
        annot_style = self.detect_style(annot_chromosomes)
        
        coord_set = set(coord_chromosomes)
        annot_set = set(annot_chromosomes)
        
        common = coord_set & annot_set
        only_coord = coord_set - annot_set
        only_annot = annot_set - coord_set
        
        return {
            "coord_style": coord_style,
            "annot_style": annot_style,
            "styles_match": coord_style == annot_style,
            "common_chromosomes": sorted(list(common)),
            "only_in_coord": sorted(list(only_coord)),
            "only_in_annot": sorted(list(only_annot)),
            "can_auto_convert": coord_style and annot_style and coord_style != annot_style
        }
    
    def get_conversion_suggestion(
        self,
        mismatch_info: Dict
    ) -> str:
        """
        Generate a user-friendly message about chromosome mismatches
        
        Args:
            mismatch_info: Output from find_mismatches()
            
        Returns:
            Suggestion message
        """
        if mismatch_info["styles_match"]:
            return "✅ Chromosome IDs match between files"
        
        coord_style = mismatch_info["coord_style"] or "unknown"
        annot_style = mismatch_info["annot_style"] or "unknown"
        
        msg = f"""
        ⚠️ Chromosome ID mismatch detected!
        
        - Coordinate file uses: **{coord_style}** style
          Examples: {', '.join(mismatch_info['only_in_coord'][:3])}
        
        - Annotation file uses: **{annot_style}** style
          Examples: {', '.join(mismatch_info['only_in_annot'][:3])}
        """
        
        if mismatch_info["can_auto_convert"]:
            msg += "\n\n✨ **Automatic conversion available!** Select 'Auto-convert' to standardize."
        else:
            msg += "\n\n⚠️ **Manual intervention required.** Please check your files."
        
        return msg.strip()
