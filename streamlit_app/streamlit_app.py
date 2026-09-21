"""
AnnotateR - Genomic Coordinate Annotation Tool

Main Streamlit application

Authors: Jyotirmoy Das, Ph.D. & Massimiliano Volpe, Ph.D.
Contact: jyotirmoy.das@liu.se
License: GNU GPLv3
"""

import sys
from pathlib import Path

# Add the streamlit_app directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import core modules
from core import (
    ChromosomeMapper,
    CoordinateConverter,
    CoordinateNormalizer,
    FormatDetector,
    BEDParser,
    GFFParser,
    VCFParser,
    CustomParser,
    AnnotationEngine,
    BedtoolsEngine,
    PolarsBioEngine,
    get_summary_stats
)
from utils import FileValidator, DataValidator, format_file_size, save_uploaded_file
from config import Settings

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


# Page configuration
st.set_page_config(
    page_title=f"{Settings.APP_NAME} - {Settings.DESCRIPTION}",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0;
        background: linear-gradient(135deg, #006DAE 0%, #0099DD 100%);
        color: white;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .info-box {
        padding: 1rem;
        background-color: #f0f7ff;
        border-left: 4px solid #006DAE;
        border-radius: 5px;
        margin: 1rem 0;
    }
    .warning-box {
        padding: 1rem;
        background-color: #fff3cd;
        border-left: 4px solid #ffc107;
        border-radius: 5px;
        margin: 1rem 0;
    }
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border-left: 4px solid #28a745;
        border-radius: 5px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main application"""
    
    # Header
    st.markdown(f"""
    <div class="main-header">
        <h1>🧬 {Settings.APP_NAME}</h1>
        <p>{Settings.DESCRIPTION}</p>
        <small>Version {Settings.VERSION}</small>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Engine Selection (New!)
        st.subheader("🚀 Processing Engine")
        engine_choice = st.selectbox(
            "Annotation Engine",
            options=["Bedtools (Standard)", "Polars-Bio (Fast, Experimental)"],
            index=0,
            help="Bedtools uses pybedtools. Polars-Bio uses a high-performance Rust backend."
        )
        
        # Coordinate system settings
        st.subheader("📐 Coordinate System")
        
        coord_system_option = st.selectbox(
            "Input coordinates",
            options=["Auto-detect", "0-based (BED)", "1-based (GFF/GTF/VCF)"],
            help="Auto-detect will determine from file format"
        )
        
        annot_system_option = st.selectbox(
            "Annotation coordinates",
            options=["Auto-detect", "0-based (BED)", "1-based (GFF/GTF/VCF)"],
            help="Auto-detect will determine from file format"
        )
        
        # Chromosome ID handling
        st.subheader("🧩 Chromosome IDs")
        
        chr_handling = st.radio(
            "Handling strategy",
            options=["Auto-convert if needed", "Manual specification"],
            help="Auto-convert will standardize chromosome IDs automatically"
        )
        
        target_chr_style = None
        if chr_handling == "Manual specification":
            target_chr_style = st.selectbox(
                "Target style",
                options=["UCSC (chr1, chr2, ...)", "Ensembl (1, 2, ...)", "Keep original"],
                help="Convert all chromosome IDs to this style"
            )
        
        # Annotation mode
        st.subheader("🎯 Annotation Mode")
        
        mode = st.selectbox(
            "Intersection mode",
            options=list(Settings.ANNOTATION_MODES.keys()),
            format_func=lambda x: f"{x.title()}: {Settings.ANNOTATION_MODES[x]['description']}"
        )
        
        # Feature type filter (for GFF/GTF files)
        st.subheader("🔬 Feature Filter")
        
        feature_types = st.multiselect(
            "Filter by feature type",
            options=["gene", "transcript", "exon", "CDS", "5UTR", "3UTR", "start_codon", "stop_codon"],
            default=["gene"],
            help="Only include these feature types from annotation file (GFF/GTF)"
        )
        
        if not feature_types:
            st.warning("⚠️ No features selected - all features will be included")
            
        # Advanced options
        with st.expander("🔧 Advanced Options"):
            use_strand = st.checkbox(
                "Consider strand information",
                help="Require same strand for overlaps"
            )
            
            min_overlap = st.slider(
                "Minimum overlap fraction",
                0.0, 1.0, 0.0, 0.1,
                help="Fraction of coordinate that must overlap (0 = any overlap)"
            )
            
            show_stats = st.checkbox(
                "Show summary statistics",
                value=True
            )
            
        settings = {
            "coord_system": coord_system_option,
            "annot_system": annot_system_option,
            "chr_handling": chr_handling,
            "target_chr_style": target_chr_style,
            "mode": mode,
            "feature_types": feature_types,
            "engine": engine_choice
        }
        
    # Main content area
    tab1, tab2, tab3 = st.tabs(["📤 Upload & Annotate", "📊 Results", "ℹ️ Help"])
    
    with tab1:
        st.markdown("### 1. Upload Files")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.info("Input Coordinates (BED, VCF, etc.)")
            coord_file = st.file_uploader("Choose coordinate file", type=["bed", "txt", "tsv", "csv", "vcf"])
            
            # Show file info if uploaded
            if coord_file:
                st.caption(f"Size: {format_file_size(coord_file.size)}")
        
        with col2:
            st.info("Annotation File (GTF, GFF, BED)")
            annot_file = st.file_uploader("Choose annotation file", type=["gtf", "gff", "gff3", "bed"])
            
            if annot_file:
                st.caption(f"Size: {format_file_size(annot_file.size)}")
                
        # Run annotation button (placeholder for logic below)
    
        # Preview files
        if coord_file or annot_file:
            with st.expander("👀 Preview Files", expanded=True):
                preview_col1, preview_col2 = st.columns(2)
                
                with preview_col1:
                    st.markdown("**Coordinate File Preview**")
                    if coord_file:
                        try:
                            # Save and parse coordinate file
                            coord_path = save_uploaded_file(coord_file)
                            coord_format = FormatDetector.detect(str(coord_path))
                            use_polars_bio = engine_choice.startswith("Polars-Bio")
                            if coord_format == "bed":
                                coord_df = BEDParser.parse(str(coord_path), use_polars_bio=use_polars_bio)
                            elif coord_format == "vcf":
                                coord_df = VCFParser.parse(str(coord_path), use_polars_bio=use_polars_bio)
                            else:
                                coord_df = CustomParser.parse(str(coord_path))
                            st.dataframe(coord_df.head(10), use_container_width=True)
                            st.caption(f"Format: {coord_format.upper()} | Rows: {len(coord_df):,}")
                            # Store in session state
                            st.session_state.coord_df = coord_df
                            st.session_state.coord_format = coord_format
                        except Exception as e:
                            st.error(f"Error parsing file: {str(e)}")
                    else:
                        st.info("Waiting for upload...")
                
                with preview_col2:
                    st.markdown("**Annotation File Preview**")
                    if annot_file:
                        try:
                            # Save and parse annotation file
                            annot_path = save_uploaded_file(annot_file)
                            annot_format = FormatDetector.detect(str(annot_path))
                            use_polars_bio = engine_choice.startswith("Polars-Bio")
                            
                            if annot_format in ["gff", "gtf"]:
                                annot_df = GFFParser.parse(str(annot_path), feature_types=feature_types, use_polars_bio=use_polars_bio)
                            elif annot_format == "bed":
                                annot_df = BEDParser.parse(str(annot_path), use_polars_bio=use_polars_bio)
                            else:
                                annot_df = CustomParser.parse(str(annot_path))
                            
                            st.dataframe(annot_df.head(10), use_container_width=True)
                            st.caption(f"Format: {annot_format.upper()} | Rows: {len(annot_df):,}")
                            
                            # Store in session state
                            st.session_state.annot_df = annot_df
                            st.session_state.annot_format = annot_format
                            
                        except Exception as e:
                            st.error(f"Error parsing file: {str(e)}")
                    else:
                        st.info("Waiting for upload...")
        
        # Column mapping for custom files
        if 'coord_df' in st.session_state and st.session_state.coord_format == "custom":
            with st.expander("🗺️ Map Coordinate Columns", expanded=True):
                coord_df = st.session_state.coord_df
                suggestions = CustomParser.suggest_columns(coord_df)
                
                map_col1, map_col2, map_col3 = st.columns(3)
                
                with map_col1:
                    chr_col = st.selectbox(
                        "Chromosome column",
                        options=coord_df.columns.tolist(),
                        index=list(coord_df.columns).index(suggestions['chr']) if suggestions['chr'] else 0
                    )
                
                with map_col2:
                    start_col = st.selectbox(
                        "Start position",
                        options=coord_df.columns.tolist(),
                        index=list(coord_df.columns).index(suggestions['start']) if suggestions['start'] else 1
                    )
                
                with map_col3:
                    end_options = ['None (single positions)'] + coord_df.columns.tolist()
                    end_col = st.selectbox(
                        "End position",
                        options=end_options,
                        index=(list(coord_df.columns).index(suggestions['end']) + 1) if suggestions['end'] else 0
                    )
                
                # Apply mapping
                if st.button("Apply Column Mapping"):
                    end_col_name = None if end_col == 'None (single positions)' else end_col
                    mapped_df = CustomParser.map_columns(coord_df, chr_col, start_col, end_col_name)
                    st.session_state.coord_df = mapped_df
                    st.success("✅ Column mapping applied!")
        
        # Similar mapping for annotation file
        if 'annot_df' in st.session_state and st.session_state.annot_format == "custom":
            with st.expander("🗺️ Map Annotation Columns", expanded=True):
                st.info("Use same process as coordinate file to map annotation columns")
        
        # Run annotation
        st.markdown("---")
        
        if st.button("🚀 Run Annotation", type="primary", use_container_width=True):
            if 'coord_df' not in st.session_state or 'annot_df' not in st.session_state:
                st.error("Please wait for files to finish parsing")
            else:
                run_annotation(
                    st.session_state.coord_df,
                    st.session_state.annot_df,
                    mode,
                    use_strand,
                    min_overlap,
                    show_stats,
                    chr_handling == "Auto-convert if needed",
                    target_chr_style,
                    feature_types,
                    engine_choice
                )
        
        # Display results from session state if available (for filter persistence)
        elif 'result_df' in st.session_state:
            display_results(
                st.session_state.result_df,
                st.session_state.result_coord_df,
                st.session_state.result_annot_df,
                st.session_state.show_stats
            )
    
    # Footer
    st.markdown("---")
    st.markdown(f"""
    <div style='text-align: center; color: #666; padding: 1rem;'>
        <p>© 2025 Developed by <strong>Jyotirmoy Das, Ph.D.</strong> & <strong>Massimiliano Volpe, Ph.D.</strong></p>
        <p>Contact: <a href='mailto:jyotirmoy.das@liu.se'>jyotirmoy.das@liu.se</a> | <a href='mailto:massimiliano.volpe@scilifelab.se'>massimiliano.volpe@scilifelab.se</a></p>
        <p>Version {Settings.VERSION} | License: GNU GPLv3</p>
        <p><em>Powered by Streamlit, pybedtools, and bedtools</em></p>
    </div>
    """, unsafe_allow_html=True)


def run_annotation(
    coord_df: pd.DataFrame,
    annot_df: pd.DataFrame,
    mode: str,
    use_strand: bool,
    min_overlap: float,
    show_stats: bool,
    auto_convert_chr: bool,
    target_chr_style: str = None,
    feature_types: list = None,
    engine_type: str = None
):
    """Execute annotation workflow"""
    
    with st.spinner("Processing..."):
        try:
            # Step 1: Validate data
            st.info("🔍 Validating data...")
            
            is_valid, error = DataValidator.validate_coordinates(coord_df)
            if not is_valid:
                st.error(f"Coordinate validation failed: {error}")
                return
            
            is_valid, error = DataValidator.validate_coordinates(annot_df)
            if not is_valid:
                st.error(f"Annotation validation failed: {error}")
                return
            
            # Step 1.5: Filter annotation by feature type
            if feature_types and 'feature' in annot_df.columns:
                original_count = len(annot_df)
                annot_df = annot_df[annot_df['feature'].isin(feature_types)]
                filtered_count = len(annot_df)
                st.info(f"🔬 Filtered annotations: {filtered_count:,} features (from {original_count:,})")
                
                if filtered_count == 0:
                    st.warning("⚠️ No annotations match the selected feature types!")
                    return
            
            # Step 2: Check chromosome compatibility
            st.info("🧩 Checking chromosome IDs...")
            
            mapper = ChromosomeMapper()
            mismatch_info = mapper.find_mismatches(
                coord_df['chr'].unique().tolist(),
                annot_df['chr'].unique().tolist()
            )
            
            if not mismatch_info['styles_match']:
                suggestion = mapper.get_conversion_suggestion(mismatch_info)
                st.warning(suggestion)
                
                if auto_convert_chr and mismatch_info['can_auto_convert']:
                    # Auto-convert to common style
                    target_style = "ucsc"
                    st.info(f"Converting chromosome IDs to {target_style} style...")
                    
                    coord_df, _, _ = mapper.standardize_dataframe(coord_df, 'chr', target_style)
                    annot_df, _, _ = mapper.standardize_dataframe(annot_df, 'chr', target_style)
                    
                    st.success("✅ Chromosome IDs standardized!")
            
            # Step 3: Annotate
            st.info(f"🎯 Running {mode} annotation...")
            
            # Select engine based on setting (passed as argument or check session/global?)
            # Ideally pass engine_type to this function
            
            if "Polars-Bio" in engine_type:
                engine = PolarsBioEngine(
                    use_strand=use_strand,
                    min_overlap=min_overlap if min_overlap > 0 else None,
                    mode=mode
                )
            else:
                engine = BedtoolsEngine(
                    use_strand=use_strand,
                    min_overlap=min_overlap if min_overlap > 0 else None,
                    mode=mode
                )
            
            result_df = engine.intersect(coord_df, annot_df, how="left")
            
            st.success(f"✅ Annotation complete! Found {len(result_df):,} results.")
            
            # Store results in session state for persistence
            st.session_state.result_df = result_df
            st.session_state.result_coord_df = coord_df
            st.session_state.result_annot_df = annot_df
            st.session_state.show_stats = show_stats
            
            # Step 4: Display results
            display_results(result_df, coord_df, annot_df, show_stats)
            
        except Exception as e:
            st.error(f"❌ Error during annotation: {str(e)}")
            st.exception(e)


def display_results(result_df: pd.DataFrame, coord_df: pd.DataFrame, annot_df: pd.DataFrame, show_stats: bool):
    """Display annotation results with charts and gene list"""
    
    st.markdown("---")
    st.subheader("📊 Results")
    
    if result_df.empty:
        st.warning("⚠️ No overlapping annotations found!")
        return
    
    # Summary statistics
    if show_stats:
        col1, col2, col3, col4 = st.columns(4)
        
        # Calculate overlap stats
        if 'has_overlap' in result_df.columns:
            overlapping = result_df['has_overlap'].sum()
            non_overlapping = len(result_df) - overlapping
        else:
            overlapping = len(result_df)
            non_overlapping = 0
        
        with col1:
            st.metric("Total Entries", f"{len(result_df):,}")
        
        with col2:
            st.metric("Overlapping", f"{overlapping:,}", 
                     help="Coordinates with annotation overlap")
        
        with col3:
            st.metric("Intergenic", f"{non_overlapping:,}",
                     help="Coordinates without annotation overlap")
        
        with col4:
            annot_rate = (overlapping / len(result_df) * 100) if len(result_df) > 0 else 0
            st.metric("Overlap Rate", f"{annot_rate:.1f}%")
    
    # Feature Distribution Charts (using full data, not filtered)
    st.markdown("### 📈 Summary Charts")
    
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        # Feature type distribution pie chart
            # Harmonize feature column detection for both engines
            feature_col_candidates = [
                'annot_feature', 'feature', 'coord_feature_2', 'coord_feature', 'feature_2'
            ]
            feature_col = next((col for col in feature_col_candidates if col in result_df.columns), None)
            if feature_col:
                valid_features = result_df[result_df[feature_col].astype(str).isin(['-1', '.', 'nan']) == False]
                if len(valid_features) > 0:
                    feature_counts = valid_features[feature_col].value_counts()
                    fig_pie = px.pie(
                        values=feature_counts.values,
                        names=feature_counts.index,
                        title="Feature Type Distribution",
                        color_discrete_sequence=px.colors.qualitative.Set2
                    )
                    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                    fig_pie.update_layout(showlegend=True, height=350)
                    st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.info("ℹ️ No feature type data available for chart")
            else:
                st.info("ℹ️ No feature type data available for chart")
    
    with chart_col2:
        # Chromosome distribution bar chart
        chr_col_candidates = [
            'coord_chr', 'chr', 'coord_chrom_1', 'coord_chrom_2', 'chrom', 'chrom_1', 'chrom_2'
        ]
        chr_col = next((col for col in chr_col_candidates if col in result_df.columns), None)
        if chr_col:
            chr_counts = result_df[chr_col].value_counts().head(15)
            fig_bar = px.bar(
                x=chr_counts.index,
                y=chr_counts.values,
                title="Annotations per Chromosome (Top 15)",
                labels={'x': 'Chromosome', 'y': 'Count'},
                color=chr_counts.values,
                color_continuous_scale='Blues'
            )
            fig_bar.update_layout(showlegend=False, height=350)
            st.plotly_chart(fig_bar, use_container_width=True)
    
    # Gene List Export
    st.markdown("### 🧬 Gene List Export")
    
    # Try to find gene names in the results - prioritize annotation columns
    gene_col = None
    # Priority order: annotation gene names > annotation IDs > coordinate names (last resort)
    possible_gene_cols = [
        # Annotation gene names (highest priority)
        'annot_Name', 'annot_gene_name', 'annot_name',
        # Raw gene names (might exist without prefix)
        'gene_name', 'Name',
        # Annotation IDs (less preferred but usable)
        'annot_gene_id', 'annot_ID', 'gene_id', 'ID',
        # Generic
        'gene', 'Gene', 'GENE', 'symbol', 'Symbol',
        # Coordinate names (lowest priority - these are YOUR region names, not gene names)
        # 'coord_name' - intentionally excluded to avoid confusion
    ]
    
    for col in possible_gene_cols:
        if col in result_df.columns:
            # For annotation columns, also check if they have valid data
            if col.startswith('annot_'):
                # Check if this column has non-null values (not all -1 or .)
                valid_values = result_df[col].dropna()
                valid_values = valid_values[~valid_values.astype(str).isin(['-1', '.', 'nan', ''])]
                if len(valid_values) > 0:
                    gene_col = col
                    break
            else:
                gene_col = col
                break

    if gene_col and len(result_df) > 0:
        # Extract unique gene names
        gene_list = result_df[gene_col].dropna().unique().tolist()
        # Filter out placeholder values
        gene_list = [g for g in gene_list if str(g) not in ['-1', '.', 'nan', '']]
        
        if gene_list:
            gene_col1, gene_col2 = st.columns([1, 1])
            with gene_col1:
                # Count genes
                top_genes = result_df[gene_col].value_counts().head(10)
                
                fig_top = px.bar(
                    x=top_genes.values,
                    y=top_genes.index,
                    orientation='h',
                    title="Top 10 (by annotation count)",
                    labels={'x': 'Count', 'y': 'Gene/Feature'},
                    color=top_genes.values,
                    color_continuous_scale='Viridis'
                )
                fig_top.update_layout(showlegend=False, height=300, yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_top, use_container_width=True)

            with gene_col2:
                st.markdown("**Quick Actions:**")
                # Gene list as text for copying
                gene_text = "\n".join(sorted(gene_list))
                st.download_button(
                    label="📥 Download Gene List (.txt)",
                    data=gene_text,
                    file_name="gene_list.txt",
                    mime="text/plain",
                    use_container_width=True
                )
                # Comma-separated for pasting
                gene_csv = ", ".join(sorted(gene_list))
                st.download_button(
                    label="📥 Comma-separated (.csv)",
                    data=gene_csv,
                    file_name="gene_list.csv",
                    mime="text/plain",
                    use_container_width=True,
                    key="gene_csv"
                )
                # Copy to clipboard blocks
                with st.expander("📋 Copy to clipboard"):
                    st.caption("One gene per line:")
                    st.code(gene_text, language="text")
                    st.caption("Comma-separated:")
                    st.code(gene_csv, language="text")
                    st.markdown("---")
                    st.markdown("**📌 Paste into:**")
                    st.markdown("• [g:Profiler](https://biit.cs.ut.ee/gprofiler)")
                    st.markdown("• [Enrichr](https://maayanlab.cloud/Enrichr)")
                    st.markdown("• [DAVID](https://davidbioinformatics.nih.gov/tools.jsp)")
                    st.markdown("• [STRING](https://string-db.org)")
        else:
            st.info("ℹ️ No valid gene names found in results")
        st.info("ℹ️ No gene name column found in results. Columns available: " + ", ".join(result_df.columns.tolist()[:10]))
    
    # Results table with filter
    st.markdown("### 📄 Annotated Data")
    
    # Filter toggle just above table
    if 'has_overlap' in result_df.columns:
        result_filter = st.radio(
            "Filter:",
            options=["All", "Overlapping only", "Intergenic only"],
            horizontal=True,
            key="result_filter"
        )
        
        # Apply filter to display dataframe
        if result_filter == "Overlapping only":
            display_df = result_df[result_df['has_overlap'] == True]
        elif result_filter == "Intergenic only":
            display_df = result_df[result_df['has_overlap'] == False]
        else:
            display_df = result_df
        
        st.caption(f"Showing {len(display_df):,} of {len(result_df):,} entries")
    else:
        display_df = result_df
    
    st.dataframe(display_df, use_container_width=True, height=400)
    
    # Download options (use filtered data)
    st.markdown("### ⬇️ Download Results")
    
    download_col1, download_col2, download_col3 = st.columns(3)
    
    with download_col1:
        csv = display_df.to_csv(index=False)
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name="annotated_coordinates.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with download_col2:
        tsv = display_df.to_csv(index=False, sep='\t')
        st.download_button(
            label="📥 Download TSV",
            data=tsv,
            file_name="annotated_coordinates.tsv",
            mime="text/tab-separated-values",
            use_container_width=True
        )
    
    with download_col3:
        # Excel download requires openpyxl
        try:
            from io import BytesIO
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                display_df.to_excel(writer, index=False, sheet_name='Annotations')
            
            st.download_button(
                label="📥 Download Excel",
                data=buffer.getvalue(),
                file_name="annotated_coordinates.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        except ImportError:
            st.caption("Excel export requires openpyxl")
    
    # VCF Download (only if input was VCF)
    if 'coord_format' in st.session_state and st.session_state.coord_format == 'vcf':
        st.markdown("### 🧬 VCF Export")
        st.info("Reconstructed VCF with annotations added to INFO field.")
        
        vcf_content = convert_df_to_vcf(display_df)
        st.download_button(
            label="📥 Download Annotated VCF",
            data=vcf_content,
            file_name="annotated_variants.vcf",
            mime="application/octet-stream",
            use_container_width=True,
            key="download_vcf"
        )


def convert_df_to_vcf(df: pd.DataFrame) -> str:
    """
    Convert results DataFrame back to VCF format.
    Reconstructs standard columns and adds annotations to INFO.
    """
    lines = [
        "##fileformat=VCFv4.2",
        "##source=AnnotatorApp",
        f"##date={pd.Timestamp.now().strftime('%Y%m%d')}",
        "##INFO=<ID=ANNOT,Number=.,Type=String,Description=\"Annotations added by AnnotatorApp formatted as Key=Value\">",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
    ]
    
    # Map internal columns to VCF standard columns
    # Note: df uses 0-based start, VCF uses 1-based POS (which equals end for SNPs)
    # So we use coord_end as POS
    
    res = df.copy()
    
    # Ensure required columns exist, fill with '.' if missing
    required_map = {
        'coord_chr': 'CHROM',
        'coord_end': 'POS',
        'coord_id': 'ID',
        'coord_ref': 'REF',
        'coord_alt': 'ALT',
        'coord_qual': 'QUAL',
        'coord_filter': 'FILTER'
    }
    
    # Check which columns we actually have
    available_map = {}
    for int_col, vcf_col in required_map.items():
        if int_col in df.columns:
            available_map[int_col] = vcf_col
        # Special handling if coord_ prefix is missing
        elif int_col.replace('coord_', '') in df.columns:
             available_map[int_col.replace('coord_', '')] = vcf_col
    
    if not available_map:
        return "##Error: Could not reconstruct VCF. Missing coordinate columns."

    # Identify annotation columns for INFO field
    annot_cols = [c for c in df.columns if c.startswith('annot_') and c not in ['annot_chr', 'annot_start', 'annot_end', 'has_overlap']]
    
    vcf_rows = []
    
    for _, row in res.iterrows():
        # Build standard fields
        fields = []
        fields.append(str(row.get('coord_chr', row.get('chr', '.'))))
        
        # POS: Convert 0-based end back to 1-based POS
        # Internal: start=9, end=10 -> VCF POS=10
        fields.append(str(row.get('coord_end', row.get('end', '.'))))
        
        fields.append(str(row.get('coord_id', row.get('id', '.'))))
        fields.append(str(row.get('coord_ref', row.get('ref', '.'))))
        fields.append(str(row.get('coord_alt', row.get('alt', '.'))))
        fields.append(str(row.get('coord_qual', row.get('qual', '.'))))
        fields.append(str(row.get('coord_filter', row.get('filter', '.'))))
        
        # Build INFO field
        info_parts = []
        
        # Add annotations
        annot_parts = []
        for col in annot_cols:
            val = str(row[col])
            if val and val not in ['.', 'nan', '-1', 'None']:
                key = col.replace('annot_', '')
                # Clean value for VCF compatibility
                clean_val = val.replace(';', '|').replace(' ', '_').replace('=', ':')
                annot_parts.append(f"{key}={clean_val}")
        
        if annot_parts:
            info_parts.append(";".join(annot_parts))
        else:
            info_parts.append(".")
            
        fields.append(";".join(info_parts))
        
        vcf_rows.append("\t".join(fields))
        
    return "\n".join(lines + vcf_rows)


if __name__ == "__main__":
    main()
