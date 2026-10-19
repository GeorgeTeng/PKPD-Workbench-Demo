# Optional generic response regression, distinct from a mechanistic PK or PD model.
fit_response_longitudinal <- function(data, response_unit, spline_df = 3L,
                                       serial_correlation = FALSE, ci_level = 0.95) {
  required_columns(data, c("subject_id", "time_h", "response", "exposure"))
  if (!is.character(response_unit) || length(response_unit) != 1L || response_unit %in% c("", "NOT_FOUND"))
    pkpd_stop("Declare response_unit.")
  assert_numeric(data$time_h, "time_h"); assert_numeric(data$response, "response")
  assert_numeric(data$exposure, "exposure", nonnegative = TRUE)
  check_blq(data)
  if (anyNA(data$subject_id) || anyDuplicated(data[c("subject_id", "time_h")])) pkpd_stop("Resolve missing IDs and duplicate subject/time pairs.")
  if (length(unique(data$subject_id)) < 3L) pkpd_stop("Random-intercept prototype requires multiple subjects (at least three for this implementation).")
  if (length(spline_df) != 1L || !spline_df %in% 1:5 || length(unique(data$time_h)) <= spline_df + 1L)
    pkpd_stop("Insufficient time support for requested spline degrees of freedom.")
  if (length(unique(data$exposure)) < 2L) pkpd_stop("An exposure association cannot be estimated from constant exposure.")
  data <- data[order(data$subject_id, data$time_h), , drop = FALSE]
  data$subject_id <- factor(data$subject_id)
  formula <- stats::as.formula(sprintf("response ~ splines::ns(time_h, df = %d) + exposure", spline_df))
  matrix <- stats::model.matrix(formula, data)
  if (qr(matrix)$rank < ncol(matrix)) pkpd_stop("Time and exposure effects are not identifiable in this design.")
  correlation <- if (serial_correlation) nlme::corCAR1(form = ~ time_h | subject_id) else NULL
  captured <- capture_fit(nlme::lme(fixed = formula, data = data, random = ~ 1 | subject_id,
                                  correlation = correlation, method = "ML", na.action = stats::na.fail,
                                  control = nlme::lmeControl(maxIter = 150, msMaxIter = 150, returnObject = FALSE)))
  fit <- captured$value
  beta <- nlme::fixef(fit)
  table <- parameter_table(beta, stats::vcov(fit), rep(FALSE, length(beta)), ci_level)
  predicted <- as.numeric(stats::predict(fit, level = 1))
  structure(list(type = "longitudinal_response", fit = fit, parameters = table,
                 data = data, predicted = predicted, response_unit = response_unit, warnings = captured$warnings,
                 diagnostics = c(fit_diagnostics(fit, data$response, predicted),
                                 list(n_subjects = length(unique(data$subject_id)),
                                      serial_correlation = serial_correlation,
                                      scope = "Associational spline/exposure regression; not a mechanistic dynamic PD model or causal effect estimate."))),
            class = "pkpd_fit")
}

predict_response_longitudinal <- function(object, newdata, individual = FALSE) {
  if (object$type != "longitudinal_response") pkpd_stop("Not a longitudinal response fit.")
  required_columns(newdata, c("time_h", "exposure"))
  assert_numeric(newdata$time_h, "time_h"); assert_numeric(newdata$exposure, "exposure", nonnegative = TRUE)
  if (any(newdata$time_h < min(object$data$time_h) | newdata$time_h > max(object$data$time_h)))
    pkpd_stop("Spline time extrapolation is not enabled; supply times within the fitted range.")
  if (individual) {
    required_columns(newdata, "subject_id")
    if (any(!as.character(newdata$subject_id) %in% as.character(object$data$subject_id))) pkpd_stop("Unknown individual; use population-level prediction.")
  }
  as.numeric(stats::predict(object$fit, newdata = newdata, level = if (individual) 1 else 0))
}

