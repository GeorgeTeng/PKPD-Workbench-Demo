pkpd_stop <- function(...) stop(..., call. = FALSE)

assert_numeric <- function(x, name, positive = FALSE, nonnegative = FALSE) {
  if (!is.numeric(x) || !length(x) || any(!is.finite(x)))
    pkpd_stop(name, " must be nonempty, finite numeric values; missing values are not silently dropped.")
  if (positive && any(x <= 0)) pkpd_stop(name, " must be strictly positive.")
  if (nonnegative && any(x < 0)) pkpd_stop(name, " must be nonnegative.")
  invisible(x)
}

assert_scalar <- function(x, name, positive = FALSE) {
  assert_numeric(x, name, positive = positive)
  if (length(x) != 1L) pkpd_stop(name, " must be a scalar.")
  invisible(x)
}

required_columns <- function(data, columns) {
  if (!is.data.frame(data) || !nrow(data)) pkpd_stop("Supply a nonempty data.frame.")
  missing <- setdiff(columns, names(data))
  if (length(missing)) pkpd_stop("Missing columns: ", paste(missing, collapse = ", "))
  invisible(data)
}

validate_meta <- function(meta, require_pk = FALSE) {
  required <- c("drug", "species", "matrix", "concentration_unit", "time_unit", "concentration_basis", "record_level", "data_origin")
  if (require_pk) required <- c(required, "dose_unit", "route")
  for (key in required) {
    value <- meta[[key]]
    if (!is.character(value) || length(value) != 1L || !nzchar(value) || value == "NOT_FOUND")
      pkpd_stop("Metadata '", key, "' must be explicitly supplied before numerical analysis.")
  }
  if (meta$concentration_unit != "mg/L" || meta$time_unit != "h")
    pkpd_stop("This prototype requires concentration mg/L and time h; convert explicitly before fitting.")
  if (!meta$concentration_basis %in% c("total", "free")) pkpd_stop("Declare concentration_basis as total or free.")
  if (!meta$record_level %in% c("individual", "summary", "model_prediction")) pkpd_stop("Unknown record_level.")
  if (!meta$data_origin %in% c("synthetic", "observed", "digitized", "model_prediction")) pkpd_stop("Unknown data_origin.")
  if (require_pk && (meta$dose_unit != "mg" || meta$route != "IV"))
    pkpd_stop("PK prototype uses IV dose in mg, CL in L/h and volumes in L.")
  invisible(meta)
}

check_blq <- function(data) {
  if ("blq" %in% names(data) && (!is.logical(data$blq) || anyNA(data$blq) || any(data$blq)))
    pkpd_stop("BLQ observations require an explicit censoring model; this prototype does not impute or discard them.")
}

validate_pk_data <- function(data, meta, population = FALSE) {
  validate_meta(meta, require_pk = TRUE)
  required_columns(data, c("subject_id", "time_h", "concentration_mg_L"))
  check_blq(data)
  if (anyNA(data$subject_id) || any(!nzchar(as.character(data$subject_id)))) pkpd_stop("Missing subject_id.")
  assert_numeric(data$time_h, "time_h")
  assert_numeric(data$concentration_mg_L, "concentration_mg_L", nonnegative = TRUE)
  if (anyDuplicated(data[c("subject_id", "time_h")])) pkpd_stop("Duplicate subject/time; resolve replicates or occasions explicitly.")
  if ("species" %in% names(data) && (anyNA(data$species) || any(as.character(data$species) != meta$species)))
    pkpd_stop("Do not pool species implicitly; data species must match declared metadata.")
  if (population && meta$record_level != "individual") pkpd_stop("Population repeated-measure fitting requires individual records.")
  if (!population && length(unique(data$subject_id)) != 1L) pkpd_stop("Individual PK fitting takes exactly one subject/profile.")
  data[order(data$subject_id, data$time_h), , drop = FALSE]
}

capture_fit <- function(expr) {
  warnings <- character()
  value <- withCallingHandlers(expr, warning = function(w) {
    warnings <<- c(warnings, conditionMessage(w))
    invokeRestart("muffleWarning")
  })
  list(value = value, warnings = unique(warnings))
}

parameter_table <- function(beta, covariance, transformed = rep(FALSE, length(beta)), level = 0.95, df = Inf) {
  if (length(level) != 1 || !is.finite(level) || level <= 0 || level >= 1) pkpd_stop("Invalid CI level.")
  if (!is.matrix(covariance) || any(!is.finite(covariance)) || any(diag(covariance) < 0))
    pkpd_stop("Parameter covariance is unavailable or invalid; do not report fabricated CIs.")
  z <- if (is.finite(df)) stats::qt((1 + level) / 2, df = df) else stats::qnorm((1 + level) / 2)
  se <- sqrt(diag(covariance))
  estimate <- ifelse(transformed, exp(beta), beta)
  lower <- ifelse(transformed, exp(beta - z * se), beta - z * se)
  upper <- ifelse(transformed, exp(beta + z * se), beta + z * se)
  original_se <- ifelse(transformed, estimate * se, se)
  data.frame(parameter = sub("^log_", "", names(beta)), estimate = unname(estimate),
             SE = unname(original_se), RSE_percent = ifelse(abs(estimate) < 1e-10, NA_real_, 100 * original_se / abs(estimate)),
             CI_lower = unname(lower), CI_upper = unname(upper), CI_level = level,
             CI_method = ifelse(transformed, "Wald on log-parameter scale", "Wald on parameter scale"),
             row.names = NULL)
}

fit_diagnostics <- function(fit, observed, predicted, log_error = FALSE) {
  r <- if (log_error) log(observed) - log(predicted) else observed - predicted
  n <- length(observed)
  ll <- tryCatch(stats::logLik(fit), error = function(e) NULL)
  k <- if (is.null(ll)) NA_real_ else attr(ll, "df")
  aic <- if (is.null(ll)) NA_real_ else stats::AIC(fit)
  list(n_observations = n, likelihood_scale = if (log_error) "log concentration" else "response",
       log_likelihood = if (is.null(ll)) NA_real_ else as.numeric(ll), n_parameters = k,
       AIC = aic, BIC = if (is.null(ll)) NA_real_ else stats::BIC(fit),
       AICc = if (is.finite(k) && n > k + 1) aic + 2 * k * (k + 1) / (n - k - 1) else NA_real_,
       RMSE_on_fit_scale = sqrt(mean(r^2)), RMSE_original_scale = sqrt(mean((observed - predicted)^2)),
       inference_limit = "Local parameter uncertainty; not external predictive accuracy or a prediction interval.")
}
