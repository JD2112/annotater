# Use a specific Shiny image to ensure compatibility
FROM rocker/shiny:4.3.3

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
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
        libmagick++-dev \
        libharfbuzz-dev \
        libfribidi-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN Rscript -e 'install.packages(c("renv"))'
COPY /renv.lock /srv/shiny-server/renv.lock
RUN Rscript -e 'setwd("/srv/shiny-server/");renv::restore();'

# Copy the app files (scripts, data, etc.)
RUN rm -rf /srv/shiny-server/*
COPY /app/ /srv/shiny-server/

# Make sure shiny has UID 999 and owns the directory
RUN SHINY_UID=$(id -u shiny 2>/dev/null || echo 0) && \
    if [ "$SHINY_UID" -ne 999 ]; then \
        userdel -r shiny || true && \
        id -u 999 &>/dev/null && userdel -r $(id -un 999) || true && \
        useradd -u 999 -m -s /bin/bash shiny; \
    fi && \
    chown -R shiny:shiny /srv/shiny-server /var/lib/shiny-server /var/log/shiny-server


# Run as shiny user
USER shiny
EXPOSE 3838

# Launch app
CMD ["/usr/bin/shiny-server"]
