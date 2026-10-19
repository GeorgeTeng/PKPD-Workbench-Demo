records_frame <- function(records) {
  if (is.null(records) || !length(records)) stop("No records supplied.", call. = FALSE)
  jsonlite::fromJSON(jsonlite::toJSON(records, auto_unbox = TRUE, null = "null", digits = NA), simplifyDataFrame = TRUE)
}

portable_pk_model <- function(fit, model_id, doses = NULL) {
  if (fit$type == "individual_pk") {
    theta <- fit$theta
    compartments <- fit$compartments
    schedule <- fit$doses
  } else {
    theta <- setNames(fit$parameters$estimate, fit$parameters$parameter)
    compartments <- 1L
    if (!is.null(doses)) schedule <- doses else {
      amount <- if (fit$meta$dose_unit == "mg/kg") "dose_mg_kg" else "dose_mg"
      schedule <- unique(data.frame(time_h=fit$data$dose_time_h, dose_mg=fit$data[[amount]], duration_h=fit$data$duration_h))
      if (nrow(schedule) != 1L) schedule <- NULL
    }
  }
  list(model_id = model_id, model_schema_version = "1.0", family = paste0(compartments, "_compartment_iv"),
    compartments = compartments, parameter_basis = if (fit$meta$dose_unit == "mg/kg") "per_kg" else "absolute",
    theta = theta, parameter_units = setNames(fit$parameters$unit, fit$parameters$parameter),
    metadata = fit$meta, doses = schedule,
    dose_coefficient_unit = fit$meta$dose_unit,
    dose_encoding = "doses.dose_mg is the legacy solver coefficient; its unit is dose_coefficient_unit (mg or mg/kg).",
    prediction_kind = if (fit$type == "individual_pk") "individual_structural_curve" else "typical_eta_zero_curve",
    parameters = fit$parameters, diagnostics = fit$diagnostics,
    observed_time_range_h = range(fit$data$time_h), warnings = as.list(fit$warnings))
}
