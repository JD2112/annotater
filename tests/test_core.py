"""
Unit tests for core functionality

Run with: pytest tests/test_core.py -v
"""

import pytest
import pandas as pd
from streamlit_app.core import (
    ChromosomeMapper,
    CoordinateConverter,
    CoordinateNormalizer,
    BEDParser,
    GFFParser
)


class TestChromosomeMapper:
    """Test chromosome ID mapping"""
    
    def test_detect_ucsc_style(self):
        """Test detection of UCSC style"""
        mapper = ChromosomeMapper()
        chroms = ["chr1", "chr2", "chr3", "chrX"]
        assert mapper.detect_style(chroms) == "ucsc"
    
    def test_detect_ensembl_style(self):
        """Test detection of Ensembl style"""
        mapper = ChromosomeMapper()
        chroms = ["1", "2", "3", "X", "MT"]
        assert mapper.detect_style(chroms) == "ensembl"
    
    def test_ucsc_to_ensembl_conversion(self):
        """Test UCSC to Ensembl conversion"""
        mapper = ChromosomeMapper()
        assert mapper.convert("chr1", "ucsc", "ensembl") == "1"
        assert mapper.convert("chrX", "ucsc", "ensembl") == "X"
        assert mapper.convert("chrM", "ucsc", "ensembl") == "MT"
    
    def test_ensembl_to_ucsc_conversion(self):
        """Test Ensembl to UCSC conversion"""
        mapper = ChromosomeMapper()
        assert mapper.convert("1", "ensembl", "ucsc") == "chr1"
        assert mapper.convert("X", "ensembl", "ucsc") == "chrX"
        assert mapper.convert("MT", "ensembl", "ucsc") == "chrM"
    
    def test_dataframe_standardization(self):
        """Test DataFrame chromosome standardization"""
        mapper = ChromosomeMapper()
        df = pd.DataFrame({
            'chr': ['chr1', 'chr2', 'chr3'],
            'start': [100, 200, 300],
            'end': [200, 300, 400]
        })
        
        result_df, source, target = mapper.standardize_dataframe(
            df, 'chr', 'ensembl'
        )
        
        assert source == "ucsc"
        assert target == "ensembl"
        assert result_df['chr'].tolist() == ['1', '2', '3']


class TestCoordinateConverter:
    """Test coordinate system conversion"""
    
    def test_zero_to_one_based(self):
        """Test 0-based to 1-based conversion"""
        start, end = CoordinateConverter.convert(100, 200, "0-based", "1-based")
        assert start == 101
        assert end == 200
    
    def test_one_to_zero_based(self):
        """Test 1-based to 0-based conversion"""
        start, end = CoordinateConverter.convert(101, 200, "1-based", "0-based")
        assert start == 100
        assert end == 200
    
    def test_same_system(self):
        """Test conversion within same system"""
        start, end = CoordinateConverter.convert(100, 200, "0-based", "0-based")
        assert start == 100
        assert end == 200
    
    def test_detect_system_from_format(self):
        """Test system detection from file format"""
        assert CoordinateConverter.detect_system("bed") == "0-based"
        assert CoordinateConverter.detect_system("gff") == "1-based"
        assert CoordinateConverter.detect_system("gtf") == "1-based"
        assert CoordinateConverter.detect_system("vcf") == "1-based"


class TestCoordinateNormalizer:
    """Test coordinate normalization"""
    
    def test_snp_normalization_zero_based(self):
        """Test SNP normalization in 0-based system"""
        chr, start, end = CoordinateNormalizer.normalize(
            "chr1", 100, None, is_snp=True, coordinate_system="0-based"
        )
        assert chr == "chr1"
        assert start == 100
        assert end == 101
    
    def test_snp_normalization_one_based(self):
        """Test SNP normalization in 1-based system"""
        chr, start, end = CoordinateNormalizer.normalize(
            "chr1", 101, None, is_snp=True, coordinate_system="1-based"
        )
        assert chr == "chr1"
        assert start == 101
        assert end == 101
    
    def test_interval_normalization(self):
        """Test interval normalization (no change)"""
        chr, start, end = CoordinateNormalizer.normalize(
            "chr1", 100, 200, is_snp=False
        )
        assert chr == "chr1"
        assert start == 100
        assert end == 200
    
    def test_is_single_position_zero_based(self):
        """Test single position detection in 0-based"""
        assert CoordinateNormalizer.is_single_position(100, 101, "0-based") == True
        assert CoordinateNormalizer.is_single_position(100, 200, "0-based") == False
    
    def test_is_single_position_one_based(self):
        """Test single position detection in 1-based"""
        assert CoordinateNormalizer.is_single_position(100, 100, "1-based") == True
        assert CoordinateNormalizer.is_single_position(100, 200, "1-based") == False


class TestParsers:
    """Test file parsers"""
    
    def test_bed_parser(self, tmp_path):
        """Test BED file parsing"""
        # Create temporary BED file
        bed_file = tmp_path / "test.bed"
        bed_file.write_text("chr1\t100\t200\nregion1\nchr2\t300\t400\tregion2\n")
        
        df = BEDParser.parse(str(bed_file))
        
        assert len(df) == 2
        assert 'chr' in df.columns
        assert 'start' in df.columns
        assert 'end' in df.columns
        assert df['chr'].tolist() == ['chr1', 'chr2']
    
    def test_bed_validation(self):
        """Test BED format validation"""
        # Valid BED
        df = pd.DataFrame({
            'chr': ['chr1', 'chr2'],
            'start': [100, 200],
            'end': [200, 300]
        })
        
        is_valid, error = BEDParser.validate(df)
        assert is_valid == True
        assert error is None
        
        # Invalid BED (start >= end)
        df_invalid = pd.DataFrame({
            'chr': ['chr1'],
            'start': [200],
            'end': [100]
        })
        
        is_valid, error = BEDParser.validate(df_invalid)
        assert is_valid == False
        assert "start >= end" in error


# Integration test
class TestIntegration:
    """Integration tests"""
    
    def test_full_workflow(self):
        """Test complete annotation workflow"""
        # Create sample data
        coords = pd.DataFrame({
            'chr': ['chr1', 'chr2'],
            'start': [100, 150],
            'end': [200, 250]
        })
        
        annots = pd.DataFrame({
            'chr': ['chr1', 'chr2'],
            'start': [50, 140],
            'end': [150, 200],
            'feature': ['gene1', 'gene2']
        })
        
        # Standardize chromosomes
        mapper = ChromosomeMapper()
        coords_std, _, _ = mapper.standardize_dataframe(coords, 'chr', 'ucsc')
        annots_std, _, _ = mapper.standardize_dataframe(annots, 'chr', 'ucsc')
        
        # Verify standardization
        assert coords_std['chr'].tolist() == ['chr1', 'chr2']
        assert annots_std['chr'].tolist() == ['chr1', 'chr2']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
