#!/usr/bin/env Rscript
# Author details
## Script name: annotate.R
## Purpose of the script: 
## Author(s): Jyotirmoy Das, Ph.D.
## Date Created: 2025-06-27
## Date Last Modified: 2025-06-27
## Copyright statement: GNU3 open license
## Contact information: jyotirmoy.das@liu.se
## Please cite:
## @article{}
## Notes:
## Please read the manual/tutorial file for the sample preparation of the analysis.


suppressPackageStartupMessages({
  library(optparse)
  library(rtracklayer)
  library(IRanges)
})

option_list <- list(
  make_option(c("-b", "--bed"), type = "character", help = "BED file"),
  make_option(c("-a", "--annotation"), type = "character", help = "GFF3 or GTF file"),
  make_option(c("-v", "--vcf"), type = "character", default = NULL, help = "Optional VCF file"),
  make_option(c("-o", "--output"), type = "character", help = "Output file")
)

opt <- parse_args(OptionParser(option_list = option_list))

# Load BED
bed_df <- read.table(opt$bed, header = FALSE, sep = "\t")
colnames(bed_df)[1:3] <- c("chr", "start", "end")
bed_ranges <- IRanges(start = bed_df$start, end = bed_df$end)

# Load annotation
annotation <- import(opt$annotation)
overlaps <- findOverlaps(IRanges(start = bed_df$start, end = bed_df$end), ranges(annotation))

# Output annotation info
annotated <- cbind(bed_df[queryHits(overlaps), ], mcols(annotation)[subjectHits(overlaps), ])
write.table(annotated, file = opt$output, sep = "\t", row.names = FALSE, quote = FALSE)
