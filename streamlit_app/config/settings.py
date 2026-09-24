"""
Application settings and configuration
"""

import os
from pathlib import Path


class Settings:
    """Application-wide settings"""
    
    # Application metadata
    APP_NAME = "AnnotateR"
    VERSION = "1.0.0"
    DESCRIPTION = "Genomic Coordinate Annotation Tool"
    
    # File handling
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 500))
    SUPPORTED_COORD_FORMATS = [".bed", ".vcf", ".txt", ".csv", ".tsv"]
    SUPPORTED_ANNOT_FORMATS = [".gff", ".gtf", ".gff3", ".bed", ".txt", ".csv", ".tsv"]
    
    # Performance settings
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 100000))
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", 4))
    ENABLE_CACHING = os.getenv("ENABLE_CACHING", "true").lower() == "true"
    
    # Temporary files
    TEMP_DIR = Path(os.getenv("TEMP_DIR", "/tmp/annotator"))
    CLEANUP_AFTER_HOURS = int(os.getenv("CLEANUP_AFTER_HOURS", 24))
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Coordinate systems
    COORDINATE_SYSTEMS = {
        "0-based": {
            "description": "Half-open interval [start, end)",
            "formats": ["bed", "bam"],
            "example": "[100, 200) = positions 100-199"
        },
        "1-based": {
            "description": "Closed interval [start, end]",
            "formats": ["gff", "gtf", "vcf", "sam"],
            "example": "[101, 200] = positions 101-200"
        }
    }
    
    # Chromosome naming conventions
    CHROMOSOME_STYLES = {
        "ucsc": {
            "pattern": r"^chr[0-9XYM]+$",
            "examples": ["chr1", "chr2", "chrX", "chrY", "chrM"],
            "description": "UCSC style (chr prefix)"
        },
        "ensembl": {
            "pattern": r"^[0-9XYMT]+$",
            "examples": ["1", "2", "X", "Y", "MT"],
            "description": "Ensembl style (no prefix)"
        },
        "ncbi": {
            "pattern": r"^NC_[0-9]+\.[0-9]+$",
            "examples": ["NC_000001.11", "NC_000023.11"],
            "description": "NCBI RefSeq accessions"
        }
    }
    
    # Annotation modes
    ANNOTATION_MODES = {
        "overlap": {
            "description": "Find annotations overlapping coordinates (any overlap)",
            "bedtools_args": {"wa": True, "wb": True}
        },
        "contains": {
            # SPEC 8.4 (Task 6C): query contains annotation. Candidates come
            # from an ordinary overlap; the containment predicate is the
            # shared canonical contains_keep_mask post-filter, not a
            # backend fraction flag.
            "description": "Return annotations fully contained within each query interval",
            "bedtools_args": {"wa": True, "wb": True}
        },
        "within": {
            # SPEC 8.5 (Task 6D): query contained within annotation. Candidates
            # come from an ordinary overlap; the containment predicate is the
            # shared canonical within_keep_mask post-filter, not a backend
            # fraction flag (bedtools -F 1.0 is the opposite direction).
            "description": "Return annotations that fully contain each query interval",
            "bedtools_args": {"wa": True, "wb": True}
        },
        "closest": {
            "description": "Find nearest annotation (even without overlap)",
            "bedtools_args": {"d": True, "t": "first"}
        }
    }
    
    # UI settings
    THEME = {
        "primaryColor": "#006DAE",
        "backgroundColor": "#FFFFFF",
        "secondaryBackgroundColor": "#F0F2F6",
        "textColor": "#262730",
        "font": "sans serif"
    }
    
    @classmethod
    def ensure_temp_dir(cls):
        """Ensure temporary directory exists"""
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        return cls.TEMP_DIR
    
    @classmethod
    def get_max_file_size_bytes(cls):
        """Get maximum file size in bytes"""
        return cls.MAX_FILE_SIZE_MB * 1024 * 1024
