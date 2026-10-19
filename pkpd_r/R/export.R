json_preserve_names <- function(value) {
  # jsonlite otherwise serializes named numeric vectors as unnamed arrays.
  if (is.data.frame(value)) return(value)
  if (is.matrix(value)) return(list(row_names = rownames(value), column_names = colnames(value),
                                    values = unname(value)))
  if (is.list(value)) return(lapply(value, json_preserve_names))
  if (is.atomic(value) && !is.null(names(value))) return(as.list(value))
  value
}

write_pkpd_json <- function(value, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(json_preserve_names(value), path, pretty = TRUE, auto_unbox = TRUE, na = "null", null = "null", digits = NA)
  invisible(path)
}

export_pkpd_fit <- function(object, directory, provenance = NULL) {
  if (!inherits(object, "pkpd_fit")) pkpd_stop("Expected a pkpd_fit object.")
  dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  saveRDS(object, file.path(directory, "model.rds"))
  utils::write.csv(object$parameters, file.path(directory, "parameters.csv"), row.names = FALSE, na = "")
  predictions <- object$data
  predictions$predicted <- object$predicted
  utils::write.csv(predictions, file.path(directory, "fitted_values.csv"), row.names = FALSE, na = "")
  write_pkpd_json(list(schema_version = "0.1", analysis_type = object$type,
                       metadata = if (is.null(object$meta)) list(response_unit = object$response_unit %||% "NOT_FOUND") else object$meta,
                       provenance = provenance %||% list(data_origin = object$meta$data_origin %||% "NOT_FOUND", source = "NOT_FOUND"),
                       parameters = object$parameters, diagnostics = object$diagnostics,
                       warnings = object$warnings, review = "PENDING_HUMAN_REVIEW",
                       scope = "Exploratory prototype fit; convergence and local CIs do not establish external predictive reliability."),
                  file.path(directory, "result.json"))
  invisible(directory)
}

`%||%` <- function(x, y) if (is.null(x)) y else x

read_pkpd_context <- function(path) {
  context <- jsonlite::read_json(path, simplifyVector = FALSE)
  if (!is.null(context$context)) context <- context$context
  required <- c("version", "objective", "study", "data", "rules", "checks", "uncertainties")
  if (!all(required %in% names(context))) pkpd_stop("Input does not match the context handoff keys.")
  context
}
