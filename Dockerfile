FROM rocker/shiny:latest

# Install system dependencies needed for Bioconductor
RUN apt-get update && apt-get install -y \
    bedtools \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    zlib1g-dev \
    libxt-dev \
    libhdf5-dev \
    libncurses-dev \
    libbz2-dev \
    liblzma-dev \
    libzstd-dev \
    && rm -rf /var/lib/apt/lists/*

# Install CRAN packages
RUN install2.r --error \
    optparse \
    DT

# Install Bioconductor packages
RUN Rscript -e "install.packages('BiocManager', repos='https://cloud.r-project.org')" \
    && Rscript -e "BiocManager::install(c('IRanges', 'rtracklayer'), ask=FALSE, update=TRUE, force=TRUE)"

RUN R -e "install.packages('bslib', repos = 'https://cloud.r-project.org')"
# Copy application files
WORKDIR /app
COPY annotater.R /app/annotater.R
COPY annotator_app.R /app/annotator_app.R

# Expose port
EXPOSE 3838

# Start Shiny App
CMD ["R", "-e", "shiny::runApp('/app/annotator_app.R', host='0.0.0.0', port=3838)"]
