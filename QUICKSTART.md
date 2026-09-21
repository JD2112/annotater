# Quick Start Guide - AnnotateR

## 🚀 Get Started in 5 Minutes

### Option 1: Docker (Recommended)

```bash
# 1. Navigate to project directory
cd /Users/masvo/Documents/repo/annotater

# 2. Build and start the application
docker-compose up --build

# 3. Open your browser
# Go to: http://localhost:8501

# 4. Stop the application
# Press Ctrl+C
```

### Option 2: Local Installation

```bash
# 1. Install bedtools (macOS)
brew install bedtools

# 2. Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Run the application
streamlit run streamlit_app/streamlit_app.py

# 5. Open your browser
# Go to: http://localhost:8501
```

---

## 📝 Try It Out

### Using Example Files

The project includes example files in `data/examples/`:
- `example_coordinates.bed` - 6 genomic regions
- `example_annotations.gff3` - Gene and exon annotations

**Steps:**
1. Open the app (http://localhost:8501)
2. Upload `example_coordinates.bed` as **Coordinate File**
3. Upload `example_annotations.gff3` as **Annotation File**
4. Click **"Run Annotation"**
5. View and download results!

---

## 🧪 Run Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=streamlit_app --cov-report=html

# View coverage report
open htmlcov/index.html
```

---

## 📂 Using Your Own Files

### Coordinate File (Required)
Upload one of:
- BED file (`.bed`)
- VCF file (`.vcf`)
- Custom CSV/TSV with chr, start, end columns

### Annotation File (Required)
Upload one of:
- GFF/GTF file (`.gff`, `.gtf`, `.gff3`)
- BED file as annotations
- Custom file from BioMart or UCSC

---

## ⚙️ Configuration Options

### Coordinate Systems
- **Auto-detect**: Let the app figure it out (recommended)
- **0-based (BED)**: For BED, BAM files
- **1-based (GFF/GTF/VCF)**: For GFF, GTF, VCF, SAM files

### Chromosome IDs
- **Auto-convert**: Automatically standardize (recommended)
- **Manual**: Choose target style (UCSC, Ensembl)

### Annotation Modes
- **Overlap**: Find any overlapping annotations (default)
- **Contains**: Annotations must contain the coordinate
- **Within**: Annotations must be within the coordinate
- **Closest**: Find nearest annotation

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Kill process on port 8501
lsof -ti:8501 | xargs kill -9

# Or use different port
streamlit run streamlit_app/streamlit_app.py --server.port=8502
```

### Import Errors
```bash
# Make sure you're in the project directory
cd /Users/masvo/Documents/repo/annotater

# Install dependencies again
pip install -r requirements.txt

# Run from project root
streamlit run streamlit_app/streamlit_app.py
```

### Docker Issues
```bash
# Rebuild without cache
docker-compose build --no-cache

# Check logs
docker-compose logs

# Remove all containers and rebuild
docker-compose down
docker-compose up --build
```

---

## 📚 Next Steps

1. **Read the Full Documentation**: See [README.md](README.md)
2. **Review the Roadmap**: See [development_roadmap.md](.gemini/antigravity/brain/*/development_roadmap.md)
3. **Understand the Architecture**: Check the walkthrough

---

## 💬 Need Help?

- **Email**: jyotirmoy.das@liu.se
- **Documentation**: See README.md
- **Issues**: Check troubleshooting section

---

**Happy Annotating! 🧬**
