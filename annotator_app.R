# Author details
## Script name: annotator_app.R
## Purpose: Shiny GUI for genomic coordinate annotation
## Author: Jyotirmoy Das, Ph.D.
## Date Created: 2025-06-27
## Last Modified: 2025-06-27
## License: GNU GPLv3
## Contact: jyotirmoy.das@liu.se

library(shiny)
library(bslib)
library(DT)

ui <- page_fluid(
  theme = bs_theme(
    bootswatch = "flatly",
    bg = "#FFFFFF",
    fg = "#000000",
    primary = "#006DAE",
    base_font = font_google("Roboto"),
    code_font = font_google("Fira Code")
  ),
  div(
    style = "text-align: center; margin-top: 20px;",
    titlePanel("🧬 AnnotateR: Genomic Coordinate Annotator")    
  ),

  tags$head(
    tags$style(HTML("
      .footer {
        padding: 10px;
        background: #f8f9fa;
        text-align: center;
        font-size: 0.9em;
        margin-top: 30px;
        border-top: 1px solid #dee2e6;
      }
    ")),
    tags$script(HTML("
      Shiny.addCustomMessageHandler('scrollToOutput', function(message) {
        const outputCard = document.querySelector('.annotated-output-card');
        if (outputCard) {
          outputCard.scrollIntoView({ behavior: 'smooth' });
        }
      });
    "))
  ),

  # File inputs
  card(
    card_header("📂 Upload Input Files"),
    fluidRow(
      column(4, fileInput("bed", "BED file", accept = ".bed")),
      column(4, fileInput("annotation", "GTF/GFF3 file", accept = c(".gtf", ".gff3"))),
      column(4, fileInput("vcf", "VCF file (optional)", accept = ".vcf"))
    ),
    textInput("output", "Output filename", value = "annotated_output.tsv"),
    actionButton("run", "🚀 Run Annotation", class = "btn-primary")
  ),

  # Previews
  fluidRow(
    column(4,
      card(
        card_header("🔍 BED Preview"),
        DT::DTOutput("bed_preview")
      )
    ),
    column(4,
      card(
        card_header("🔍 Annotation Preview"),
        DT::DTOutput("annotation_preview")
      )
    ),
    column(4,
      card(
        card_header("🔍 VCF Preview"),
        DT::DTOutput("vcf_preview")
      )
    )
  ),

  # Output
  card(
    class = "annotated-output-card",
    card_header("📄 Annotated Output"),
    uiOutput("progress"),
    DT::DTOutput("preview"),
    downloadButton("download", "⬇️ Download Annotated File", class = "btn-success")
  ),

  # Footer
  div(class = "footer",
      HTML("© 2025 Conceptualized & Developed by <strong>Jyotirmoy Das, Ph.D.</strong> & <strong>Massimiliano Volpe, Ph.D.</strong> | Contact: <a href='mailto:jyotirmoy.das@liu.se'>jyotirmoy.das@liu.se</a> | Created with R & Shiny, <strong>Version 0.1.0</strong>")
  )
)

server <- function(input, output, session) {
  output_data <- reactiveVal(NULL)
  output_file_path <- reactiveVal(NULL)

  # Validate file formats
  validate_file <- function(input_file, expected_ext) {
    req(input_file)
    ext <- tools::file_ext(input_file$name)
    if (!tolower(ext) %in% expected_ext) {
      showModal(modalDialog(
        title = "Invalid File Format",
        paste("Expected file with extension:", paste(expected_ext, collapse = ", ")),
        easyClose = TRUE,
        footer = NULL
      ))
      return(FALSE)
    }
    return(TRUE)
  }

  # Previews
  output$bed_preview <- DT::renderDT({
    if (!validate_file(input$bed, "bed")) return(NULL)
    read.table(input$bed$datapath, header = FALSE)
  })

  output$annotation_preview <- DT::renderDT({
    if (!validate_file(input$annotation, c("gtf", "gff3"))) return(NULL)
    read.table(input$annotation$datapath, header = FALSE, nrows = 20)
  })

  output$vcf_preview <- DT::renderDT({
    if (!is.null(input$vcf) && validate_file(input$vcf, "vcf")) {
      read.table(input$vcf$datapath, comment.char = "#", header = FALSE)
    }
  })

  observeEvent(input$run, {
    req(input$bed, input$annotation)

    if (!validate_file(input$bed, "bed") || !validate_file(input$annotation, c("gtf", "gff3"))) return()

    bed_path <- input$bed$datapath
    ann_path <- input$annotation$datapath
    vcf_path <- if (!is.null(input$vcf)) input$vcf$datapath else NULL
    output_path <- file.path(tempdir(), input$output)
    output_file_path(output_path)

    output$progress <- renderUI({
      withProgress(message = 'Running annotation...', value = 0.1, {
        incProgress(0.2)

        cmd <- sprintf(
          "Rscript /app/annotater.R -b %s -a %s %s -o %s",
          shQuote(bed_path),
          shQuote(ann_path),
          if (!is.null(vcf_path)) paste("-v", shQuote(vcf_path)) else "",
          shQuote(output_path)
        )

        system(cmd)
        incProgress(0.7)

        if (file.exists(output_path)) {
          df <- read.table(output_path, header = TRUE)
          output_data(df)
          session$sendCustomMessage("scrollToOutput", list())
        } else {
          output_data(NULL)
        }

        incProgress(1)
      })
    })
  })

  output$preview <- DT::renderDT({
    req(output_data())
    output_data()
  })

  output$download <- downloadHandler(
    filename = function() input$output,
    content = function(file) {
      req(output_file_path())
      file.copy(output_file_path(), file)
    }
  )
}

shinyApp(ui, server)
