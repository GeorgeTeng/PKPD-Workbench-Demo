# Explicit TEST-only source selection. No statistics, generated code, or EV.
args <- commandArgs(trailingOnly = TRUE)
lib <- Sys.getenv("PKPD_R_LIB", unset = "C:/Users/georg/Documents/Codex/ScienceEnv/R-library")
if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
if (!requireNamespace("jsonlite", quietly = TRUE)) stop("TEST jsonlite dependency unavailable", call. = FALSE)

select_source_rows <- function(task) {
  stopifnot(identical(task$contract, "EP_EC_TASK_1.0"),
            identical(task$parameters$value_handling, "SOURCE_UNCHANGED"),
            identical(task$transform_aggregation_order$transform, "NONE"),
            identical(task$transform_aggregation_order$aggregation, "NONE"),
            identical(task$censoring_policy$mode, "PRESERVE_RAW_NO_IMPUTATION"),
            identical(task$input_relationships$mode, "WITHIN_SOURCE_ROW_ONLY"),
            identical(task$input_relationships$cross_dataset_join, FALSE))
  selection <- task$record_selection
  rows <- Filter(function(row) {
    identical(row$dataset_id, selection$dataset_id) && identical(row$row_type, "SOURCE_ROW") &&
      row$source_row %in% unlist(selection$row_numbers, use.names = FALSE)
  }, task$source_rows)
  stopifnot(length(rows) == length(selection$row_numbers))
  rows <- lapply(rows, function(row) {
    row$cells <- Filter(function(cell) cell$column %in% unlist(selection$columns, use.names = FALSE), row$cells)
    stopifnot(length(row$cells) == length(selection$columns),
              all(vapply(row$cells, function(cell) is.character(cell$raw_value), logical(1))))
    row$row_source_ids <- unname(lapply(row$cells, function(cell) cell$source_id))
    row
  })
  list(analysis_id = task$analysis_id, operation_id = task$operation_id,
       result_kind = "SOURCE_ROW_SELECTION_NOT_COMPUTED_STATISTICS", computed_statistics = FALSE,
       rows = rows, experimental_unit = task$experimental_unit, grouping = task$grouping,
       transform_aggregation_order = task$transform_aggregation_order,
       censoring_policy = task$censoring_policy, input_relationships = task$input_relationships,
       parameters = task$parameters, source_context = task$source_context)
}

OBSERVATION_PASSTHROUGH <- function(task) select_source_rows(task)
REPORTED_MEAN_SD_DISPLAY <- function(task) select_source_rows(task)
MIC_TABLE <- function(task) select_source_rows(task)
handlers <- list(OBSERVATION_PASSTHROUGH = OBSERVATION_PASSTHROUGH,
                 REPORTED_MEAN_SD_DISPLAY = REPORTED_MEAN_SD_DISPLAY, MIC_TABLE = MIC_TABLE)

if (identical(args, "--check")) {
  cat(jsonlite::toJSON(list(status = "TEST_SOURCE_ROW_HANDLERS_LOADED", handler_version = "TEST_SOURCE_ROWS_1.0",
      operations = unname(as.list(names(handlers))), production_enabled = FALSE,
      calculations_run = FALSE, figures_rendered = FALSE), auto_unbox = TRUE), "\n")
} else {
  if (length(args) != 3L) stop("Usage: test_source_rows.R request.json results.json results.rds", call. = FALSE)
  request <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
  stopifnot(identical(request$version, "EP_EC_DISPATCH_TEST_1.0"),
            identical(request$status, "TEST_ONLY_NOT_PRODUCTION_ASSESSMENT"),
            identical(request$handler_version, "TEST_SOURCE_ROWS_1.0"))
  results <- lapply(request$tasks, function(task) {
    if (!task$operation_id %in% names(handlers)) stop("TEST operation unavailable", call. = FALSE)
    handlers[[task$operation_id]](task)
  })
  result <- list(version = "EP_EC_RESULT_TEST_1.0", handler_version = "TEST_SOURCE_ROWS_1.0",
                 result_kind = "SOURCE_SELECTION_ONLY", computed_statistics = FALSE,
                 figures_rendered = FALSE, production_enabled = FALSE,
                 r_version = R.version.string, results = results)
  saveRDS(result, args[[3]])
  jsonlite::write_json(result, args[[2]], auto_unbox = TRUE, pretty = TRUE, na = "null", null = "null")
}
