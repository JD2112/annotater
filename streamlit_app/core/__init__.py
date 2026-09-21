"""Core functionality modules"""

from .chromosome import ChromosomeMapper
from .coordinates import CoordinateConverter, CoordinateNormalizer
from .parsers import (
    FormatDetector,
    BEDParser,
    GFFParser,
    VCFParser,
    CustomParser
)
from .annotator import (
    AnnotationEngine,
    BedtoolsEngine,
    PolarsBioEngine,
    get_summary_stats
)

__all__ = [
    "ChromosomeMapper",
    "CoordinateConverter",
    "CoordinateNormalizer",
    "FormatDetector",
    "BEDParser",
    "GFFParser",
    "VCFParser",
    "CustomParser",
    "AnnotationEngine",
    "BedtoolsEngine",
    "PolarsBioEngine",
    "get_summary_stats",
]
