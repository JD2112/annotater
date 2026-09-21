"""Core functionality modules"""

from core.chromosome import ChromosomeMapper
from core.coordinates import CoordinateConverter, CoordinateNormalizer
from core.parsers import (
    FormatDetector,
    BEDParser,
    GFFParser,
    VCFParser,
    CustomParser
)
from core.annotator import (
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
