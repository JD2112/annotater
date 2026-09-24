# AnnotateR - Genomic Coordinate Annotation Tool

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-red.svg)](https://streamlit.io/)

A web-based tool for annotating genomic coordinates with support for multiple file formats, automatic chromosome ID standardization, and coordinate system conversion.

## Features

✨ **Key Capabilities:**

- 📁 **Multiple Format Support**: BED, GFF, GTF, VCF, BioMart, UCSC Table Browser, custom CSV/TSV
- 🧩 **Chromosome ID Standardization**: Auto-detect and convert between UCSC (chr1), Ensembl (1), and NCBI styles
- 📐 **Coordinate System Handling**: Automatic conversion between 0-based and 1-based systems
- 🎯 **Multiple Annotation Modes**: Overlap, contains, within, closest feature
- ⚡ **Fast Processing**: Uses bedtools C++ backend for performance
- 🔍 **SNP Support**: Handle both single positions and genomic intervals
- 📊 **Interactive UI**: Modern Streamlit interface with real-time previews
- 🐳 **Docker Ready**: Containerized for easy deployment

## Quick Start

### Using Docker (Recommended)

```bash
# Clone repository
git clone https://github.com/your-org/annotater.git
cd annotater

# Build and run with Docker Compose
docker-compose up

# Access at http://localhost:8501
```

### Local Installation

```bash
# Install system dependencies (macOS)
brew install bedtools

# Or on Linux
sudo apt-get install bedtools

# Install Python dependencies
pip install -r requirements.txt

# Run application
streamlit run streamlit_app/streamlit_app.py
```

## Usage

1. **Upload Files**
   - Upload your coordinate file (BED, VCF, or custom format)
   - Upload your annotation file (GFF, GTF, or custom format)

2. **Configure Settings** (optional)
   - Coordinate system (auto-detected by default)
   - Chromosome ID handling (auto-converted by default)
   - Annotation mode (overlap, contains, within, closest)

3. **Run Annotation**
   - Click "Run Annotation"
   - View results in interactive table
   - Download as CSV, TSV, or Excel

### Example

```python
# Coordinate file (BED format):
chr1    100000  100500  region1
chr2    200000  200300  region2

# Annotation file (GFF format):
chr1    RefSeq  gene    50000   150000  .   +   .   gene_id "GENE1"
chr1    RefSeq  exon    99000   101000  .   +   .   gene_id "GENE1"

# Result: Coordinates annotated with overlapping genes/features
```

## Supported File Formats

### Input Coordinates
- **BED**: BED3, BED6, BED12
- **VCF**: Variant call format
- **Custom**: Any TSV/CSV with chr, start, end columns

### Annotations
- **GFF/GTF**: GFF2, GFF3, GTF
- **BED**: BED format as annotation source
- **BioMart**: Exports from Ensembl BioMart
- **UCSC**: Table Browser downloads
- **Custom**: Any delimited file with genomic coordinates

## Chromosome ID Handling

AnnotateR automatically detects and converts between different naming conventions:

| Convention | Example | Description |
|------------|---------|-------------|
| UCSC | chr1, chr2, chrX, chrY, chrM | UCSC Genome Browser style |
| Ensembl | 1, 2, X, Y, MT | Ensembl/GENCODE style |
| NCBI | NC_000001.11 | RefSeq accessions |

**Automatic conversion** ensures your files are compatible even if they use different styles!

## Coordinate Systems

| System | Format | Interval Type | Example |
|--------|--------|---------------|---------|
| 0-based | BED, BAM | Half-open [start, end) | [100, 200) = positions 100-199 |
| 1-based | GFF, GTF, VCF, SAM | Closed [start, end] | [101, 200] = positions 101-200 |

AnnotateR automatically converts coordinates based on file format detection.

## Annotation Modes

1. **Overlap** (default): Find annotations with any overlap
2. **Contains**: Return annotations fully contained within each query interval (query contains annotation)
3. **Within**: Find annotations completely within coordinates
4. **Closest**: Find nearest annotation (even without overlap)

## Architecture

```
annotator/
├── streamlit_app/
│   ├── streamlit_app.py       # Main Streamlit application
│   ├── core/                   # Core logic modules
│   │   ├── parsers.py          # File format parsers
│   │   ├── chromosome.py       # Chromosome ID handling
│   │   ├── coordinates.py      # Coordinate system conversion
│   │   └── annotator.py        # Annotation engine
│   ├── utils/                  # Utility functions
│   │   ├── validators.py       # Input validation
│   │   └── helpers.py          # Helper functions
│   └── config/
│       └── settings.py         # Configuration
├── app/                        # legacy Shiny app
├── tests/                      # Unit tests
├── data/examples/              # example files
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Development

### Running Tests

```bash
pytest tests/ -v --cov=streamlit_app
```

### Code Formatting

```bash
black streamlit_app/
ruff check streamlit_app/
```

### Adding New File Parsers

1. Create parser class in `streamlit_app/core/parsers.py`
2. Implement `parse()` method returning pandas DataFrame
3. Add to `FormatDetector.detect()` method
4. Update documentation

## Deployment

### SciLifeLab Serve

```bash
# Build image
docker build -t annotator:latest .

# Tag for SciLifeLab registry
docker tag annotator:latest registry.serve.scilifelab.se/annotator:latest

# Push to registry
docker push registry.serve.scilifelab.se/annotator:latest

# Deploy (follow SciLifeLab serve guidelines)
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_FILE_SIZE_MB` | 500 | Maximum upload file size |
| `CHUNK_SIZE` | 100000 | Rows per chunk for large files |
| `LOG_LEVEL` | INFO | Logging verbosity |
| `TEMP_DIR` | /tmp/annotator | Temporary file directory |

## Performance

Benchmarks on typical genomics files (MacBook Pro M1):

| Operation | File Size | Time |
|-----------|-----------|------|
| Load BED | 100K lines | 0.5s |
| Load GFF | 50K features | 1.2s |
| Intersect | 100K × 50K | 1.8s |
| Export TSV | 150K results | 0.4s |

**Memory usage**: ~5x file size (e.g., 100MB file → ~500MB RAM)

## Troubleshooting

### "No overlaps found"
- Check chromosome ID mismatch (e.g., "chr1" vs "1")
- Enable auto-convert in settings
- Verify coordinate systems (0-based vs 1-based)

### "File too large"
- Increase `MAX_FILE_SIZE_MB` environment variable
- Use GFF feature filtering to reduce annotation size
- Process in chunks for very large files

### Docker issues
- Ensure Docker daemon is running
- Check port 8501 is not in use: `lsof -i :8501`
- View logs: `docker-compose logs streamlit`

## Citation

If you use AnnotateR in your research, please cite:

```
Das, J. & Volpe, M. (2025). AnnotateR: A web-based tool for genomic coordinate annotation.
```

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE)

## Authors

- **Jyotirmoy Das, Ph.D.** - Conceptualization & Development
- **Massimiliano Volpe, Ph.D.** - Conceptualization & Development

## Contact

For questions, bug reports, or feature requests:
- Email: [jyotirmoy.das@liu.se](mailto:jyotirmoy.das@liu.se) | [massimiliano.volpe@scilifelab.se](mailto:massimiliano.volpe@scilifelab.se)
- Issues: GitHub Issues

## Acknowledgments

- SciLifeLab for hosting and support
- bedtools team for the fast intersection engine
- Streamlit team for the amazing web framework
- The bioinformatics community for feedback and testing

---

**Built with ❤️ for the bioinformatics community**
