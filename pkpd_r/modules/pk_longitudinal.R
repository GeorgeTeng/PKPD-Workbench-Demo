run_pk_longitudinal <- function(request, output_dir) {
  data <- records_frame(request$records)
  meta <- request$metadata
  options <- request$options
  mode <- options$mode %||% "individual"
  compartments <- options$compartments %||% 1L
  error_model <- options$error_model %||% "lognormal"
  start <- if (is.null(options$start)) NULL else unlist(options$start)
  schedule <- if (is.null(request$doses)) NULL else records_frame(request$doses)
  fits <- list()
  if (mode == "individual") {
    if (is.null(schedule)) stop("Individual PK requires a dose schedule.")
    required_columns(data, c("subject_id", "time_h", "concentration_mg_L"))
    if (anyNA(data$subject_id) || any(!nzchar(as.character(data$subject_id)))) stop("Missing subject_id; records cannot be silently dropped before splitting.")
    if ("subject_id" %in% names(schedule)) stop("Individual mode currently accepts a common schedule; use separate steps for subject-specific schedules.")
    groups <- split(data, data$subject_id)
    if (!length(groups)) stop("Missing subject_id.")
    for (j in seq_along(groups)) {
      d <- groups[[j]]
      fit <- if (identical(meta$dose_unit, "mg/kg")) {
        fit_pk_per_kg(d, schedule, meta, compartments, error_model, start)
      } else fit_pk_individual(d, schedule, meta, compartments, error_model, start)
      fits[[paste0("individual_", j)]] <- fit
    }
  } else if (mode == "population_bolus") {
    if (compartments != 1L || error_model != "lognormal") stop("Population bolus interface currently supports one compartment and lognormal error.")
    fits$population <- fit_population_pk(data, meta, start)
  } else if (mode == "population_infusion_per_kg") {
    if (compartments != 1L || error_model != "lognormal") stop("Population infusion interface currently supports one compartment and lognormal error.")
    if (is.null(start)) stop("Supply positive per-kg start values CL and V.")
    fits$population <- fit_population_pk_infusion_per_kg(data, meta, start)
  } else stop("Unsupported pk_longitudinal mode.")
  models <- list()
  for (id in names(fits)) {
    export_pkpd_fit(fits[[id]], file.path(output_dir, "models", id), request$provenance)
    models[[id]] <- portable_pk_model(fits[[id]], id, schedule)
  }
  list(models = unname(models), fitted_model_count = length(fits),
       observations_used = nrow(data), subjects = length(unique(data$subject_id)),
       downstream = "Portable PK parameter JSON for downstream prediction or translation. Index comparison is an independent branch; optional from_pk helper calculates exposures only.",
       interpretation = "Model estimates and local uncertainty; external predictive reliability remains to be assessed.")
}
