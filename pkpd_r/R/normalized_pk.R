# A unit transformation, not an assumed animal weight. Dose/W in mg/kg and
# CL/W, V/W produce exactly the same concentration as absolute dose, CL and V.
fit_pk_per_kg <- function(data, doses_per_kg, meta, compartments = 1L,
                          error = "lognormal", start = NULL, ci_level = 0.95) {
  if (!identical(meta$dose_unit, "mg/kg")) pkpd_stop("Normalized fit requires dose_unit='mg/kg'.")
  required_columns(doses_per_kg, c("time_h", "dose_mg_kg", "duration_h"))
  internal_doses <- data.frame(time_h = doses_per_kg$time_h,
                               dose_mg = doses_per_kg$dose_mg_kg,
                               duration_h = doses_per_kg$duration_h)
  # Reuse the existing analytical solver in a reference coordinate system.
  # No per-animal mass is supplied or inferred by this operation.
  internal_meta <- meta; internal_meta$dose_unit <- "mg"
  object <- fit_pk_individual(data, internal_doses, internal_meta, compartments, error, start, ci_level)
  object$meta <- meta
  object$doses_per_kg <- doses_per_kg
  object$parameter_basis <- "per kg body mass"
  object$parameters$unit <- ifelse(object$parameters$parameter %in% c("CL", "Q"), "L/h/kg", "L/kg")
  object$diagnostics$normalization <- "Parameters and internal dose coefficients are mass-normalized. No animal weight was assumed."
  object$diagnostics$internal_dose_column <- "Legacy internal dose_mg coefficients represent dose_mg_kg for this normalized fit; use doses_per_kg for interpretation."
  object
}

fit_population_pk_infusion_per_kg <- function(data, meta, start, ci_level = 0.95) {
  if (!identical(meta$dose_unit, "mg/kg") || !identical(meta$regimen_type, "single_dose"))
    pkpd_stop("Declare mg/kg and single_dose for the normalized infusion model.")
  internal_meta <- meta; internal_meta$dose_unit <- "mg"
  data <- validate_pk_data(data, internal_meta, population = TRUE)
  required_columns(data, c("dose_mg_kg", "dose_time_h", "duration_h"))
  assert_numeric(data$dose_mg_kg, "dose_mg_kg", positive = TRUE)
  assert_numeric(data$duration_h, "duration_h", positive = TRUE)
  assert_numeric(data$dose_time_h, "dose_time_h")
  if (any(data$time_h < data$dose_time_h + data$duration_h)) pkpd_stop("This population formula requires post-infusion observations.")
  if (any(data$concentration_mg_L <= 0)) pkpd_stop("Positive quantified observations required.")
  groups <- split(data, data$subject_id)
  if (length(groups) < 3L || any(vapply(groups, nrow, integer(1)) < 3L)) pkpd_stop("Insufficient subjects/time points for this implementation.")
  for (g in groups) if (nrow(unique(g[c("dose_mg_kg", "dose_time_h", "duration_h")])) != 1L)
    pkpd_stop("Single-dose history must be constant within subject.")
  if (!setequal(names(start), c("CL", "V"))) pkpd_stop("Supply per-kg start CL and V.")
  assert_numeric(start, "start", positive = TRUE)
  data$subject_id <- factor(data$subject_id)
  captured <- capture_fit(nlme::nlme(
    log(concentration_mg_L) ~ log(dose_mg_kg / duration_h) - log_CL +
      log(-expm1(-exp(log_CL - log_V) * duration_h)) -
      exp(log_CL - log_V) * (time_h - dose_time_h - duration_h),
    data = data, fixed = log_CL + log_V ~ 1, random = nlme::pdDiag(log_CL + log_V ~ 1), groups = ~ subject_id,
    start = c(log_CL = log(start[["CL"]]), log_V = log(start[["V"]])), method = "ML", na.action = stats::na.fail,
    control = nlme::nlmeControl(maxIter = 200, pnlsMaxIter = 40, msMaxIter = 200, returnObject = FALSE)))
  fit <- captured$value
  table <- parameter_table(nlme::fixef(fit), stats::vcov(fit), c(TRUE, TRUE), ci_level)
  table$unit <- c("L/h/kg", "L/kg")
  predicted <- exp(as.numeric(stats::predict(fit, level = 1)))
  structure(list(type = "population_pk_infusion_per_kg", fit = fit, meta = meta,
    parameters = table, data = data, predicted = predicted, warnings = captured$warnings,
    covariance_log_parameters = stats::vcov(fit), random_effects = nlme::ranef(fit),
    variance_components = as.data.frame(unclass(nlme::VarCorr(fit))),
    diagnostics = c(fit_diagnostics(fit, data$concentration_mg_L, predicted, TRUE),
      list(n_subjects = length(groups), parameter_basis = "per kg body mass",
        structure = "One-compartment single finite infusion; independent log-CL/log-V random effects; lognormal residuals",
        prediction_scale = "Conditional median; not population mean"))), class = "pkpd_fit")
}

predict_population_pk_infusion_per_kg <- function(object, newdata, individual = FALSE) {
  if (object$type != "population_pk_infusion_per_kg") pkpd_stop("Wrong model type.")
  required_columns(newdata, c("time_h", "dose_mg_kg", "dose_time_h", "duration_h"))
  assert_numeric(newdata$time_h, "time_h")
  assert_numeric(newdata$dose_time_h, "dose_time_h")
  assert_numeric(newdata$dose_mg_kg, "dose_mg_kg", positive = TRUE)
  assert_numeric(newdata$duration_h, "duration_h", positive = TRUE)
  beta <- nlme::fixef(object$fit)
  log_cl <- rep(beta[["log_CL"]], nrow(newdata)); log_v <- rep(beta[["log_V"]], nrow(newdata))
  if (individual) {
    required_columns(newdata, "subject_id")
    eta <- nlme::ranef(object$fit); rows <- match(as.character(newdata$subject_id), rownames(eta))
    if (anyNA(rows)) pkpd_stop("Unknown individual; use typical prediction.")
    log_cl <- log_cl + eta[rows, "log_CL"]; log_v <- log_v + eta[rows, "log_V"]
  }
  rate <- exp(log_cl - log_v); elapsed <- pmax(0, newdata$time_h - newdata$dose_time_h)
  newdata$dose_mg_kg / newdata$duration_h / exp(log_cl) *
    (-expm1(-rate * pmin(elapsed, newdata$duration_h))) * exp(-rate * pmax(elapsed - newdata$duration_h, 0))
}
