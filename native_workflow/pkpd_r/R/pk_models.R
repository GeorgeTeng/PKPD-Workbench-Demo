validate_doses <- function(doses) {
  required_columns(doses, c("time_h", "dose_mg", "duration_h"))
  assert_numeric(doses$time_h, "dose time_h")
  assert_numeric(doses$dose_mg, "dose_mg", positive = TRUE)
  assert_numeric(doses$duration_h, "duration_h", nonnegative = TRUE)
  doses[order(doses$time_h), , drop = FALSE]
}

# Unit input response for an exponential component; t=bolus time is post-dose.
iv_component <- function(time_h, rate, amplitude, doses) {
  answer <- rep(0, length(time_h))
  for (j in seq_len(nrow(doses))) {
    elapsed <- time_h - doses$time_h[j]
    active <- elapsed >= 0
    t <- pmax(0, elapsed)
    amount <- doses$dose_mg[j]; duration <- doses$duration_h[j]
    contribution <- if (duration == 0) amplitude * amount * exp(-rate * t) else
      amplitude * (amount / duration) * (-expm1(-rate * pmin(t, duration))) / rate * exp(-rate * pmax(t - duration, 0))
    answer <- answer + ifelse(active, contribution, 0)
  }
  answer
}

pk_1cpt <- function(time_h, CL_L_h, V_L, doses) {
  assert_numeric(time_h, "time_h")
  assert_scalar(CL_L_h, "CL_L_h", positive = TRUE); assert_scalar(V_L, "V_L", positive = TRUE)
  doses <- validate_doses(doses)
  iv_component(time_h, CL_L_h / V_L, 1 / V_L, doses)
}

pk_2cpt <- function(time_h, CL_L_h, Vc_L, Q_L_h, Vp_L, doses) {
  assert_numeric(time_h, "time_h")
  for (name in c("CL_L_h", "Vc_L", "Q_L_h", "Vp_L")) assert_scalar(get(name), name, positive = TRUE)
  doses <- validate_doses(doses)
  k10 <- CL_L_h / Vc_L; k12 <- Q_L_h / Vc_L; k21 <- Q_L_h / Vp_L
  total <- k10 + k12 + k21
  root <- sqrt(max(0, total^2 - 4 * k10 * k21))
  alpha <- (total + root) / 2
  beta <- 2 * k10 * k21 / (total + root)
  if (alpha - beta < .Machine$double.eps * total) pkpd_stop("Degenerate two-compartment rates.")
  a <- (alpha - k21) / (Vc_L * (alpha - beta))
  b <- (k21 - beta) / (Vc_L * (alpha - beta))
  iv_component(time_h, alpha, a, doses) + iv_component(time_h, beta, b, doses)
}

fit_pk_individual <- function(data, doses, meta, compartments = 1L,
                              error = c("lognormal", "additive"), start = NULL, ci_level = 0.95) {
  data <- validate_pk_data(data, meta)
  doses <- validate_doses(doses)
  error <- match.arg(error)
  if (!compartments %in% c(1L, 2L)) pkpd_stop("compartments must be 1 or 2.")
  n_parameters <- if (compartments == 1L) 2L else 4L
  if (nrow(data) <= n_parameters + 1L) pkpd_stop("Insufficient observations for model residual degrees of freedom.")
  if (error == "lognormal" && any(data$concentration_mg_L <= 0)) pkpd_stop("Lognormal error requires positive concentrations; zero/BLQ needs explicit handling.")
  if (is.null(start)) {
    times <- data$time_h; c <- pmax(data$concentration_mg_L, 1e-10)
    rate <- max(0.01, -as.numeric(stats::coef(stats::lm(log(c) ~ times))[2]))
    v <- doses$dose_mg[1] / max(c)
    start <- if (compartments == 1L) c(CL = rate * v, V = v) else c(CL = rate * v, Vc = v, Q = rate * v, Vp = 2 * v)
  }
  expected <- if (compartments == 1L) c("CL", "V") else c("CL", "Vc", "Q", "Vp")
  if (!setequal(names(start), expected)) pkpd_stop("start must contain: ", paste(expected, collapse = ", "))
  start <- start[expected]; assert_numeric(start, "start", positive = TRUE)
  model_fun <- function(time_h, log_CL, log_V = NULL, log_Vc = NULL, log_Q = NULL, log_Vp = NULL) {
    if (compartments == 1L) pk_1cpt(time_h, exp(log_CL), exp(log_V), doses) else
      pk_2cpt(time_h, exp(log_CL), exp(log_Vc), exp(log_Q), exp(log_Vp), doses)
  }
  initial_prediction <- do.call(model_fun, c(list(time_h = data$time_h), as.list(setNames(log(start), paste0("log_", expected)))))
  if (error == "lognormal" && any(initial_prediction <= 0)) pkpd_stop("Log fit includes pre-dose or zero predicted concentrations.")
  lhs <- if (error == "lognormal") "log(concentration_mg_L)" else "concentration_mg_L"
  rhs <- if (compartments == 1L) "model_fun(time_h, log_CL, log_V = log_V)" else
    "model_fun(time_h, log_CL, log_Vc = log_Vc, log_Q = log_Q, log_Vp = log_Vp)"
  if (error == "lognormal") rhs <- paste0("log(", rhs, ")")
  formula <- stats::as.formula(paste(lhs, "~", rhs), env = environment())
  initial <- as.list(setNames(log(start), paste0("log_", expected)))
  captured <- capture_fit(minpack.lm::nlsLM(formula, data = data, start = initial,
                        control = minpack.lm::nls.lm.control(maxiter = 300), model = TRUE))
  fit <- captured$value
  if (!isTRUE(fit$convInfo$isConv)) pkpd_stop("PK optimizer did not converge.")
  beta <- stats::coef(fit)
  theta <- setNames(exp(beta), expected)
  predicted <- if (compartments == 1L) pk_1cpt(data$time_h, theta["CL"], theta["V"], doses) else
    pk_2cpt(data$time_h, theta["CL"], theta["Vc"], theta["Q"], theta["Vp"], doses)
  table <- parameter_table(beta, stats::vcov(fit), rep(TRUE, length(beta)), ci_level, stats::df.residual(fit))
  table$unit <- ifelse(table$parameter %in% c("CL", "Q"), "L/h", "L")
  structure(list(type = "individual_pk", fit = fit, compartments = compartments, parameters = table,
                 covariance_log_parameters = stats::vcov(fit), theta = theta, doses = doses, meta = meta,
                 error_model = error, data = data, predicted = predicted, warnings = captured$warnings,
                 diagnostics = fit_diagnostics(fit, data$concentration_mg_L, predicted, error == "lognormal")),
            class = "pkpd_fit")
}

predict_pk <- function(object, time_h, doses = object$doses) {
  if (object$type != "individual_pk") pkpd_stop("Use predict_population_pk for a population model.")
  p <- object$theta
  if (object$compartments == 1L) pk_1cpt(time_h, p["CL"], p["V"], doses) else
    pk_2cpt(time_h, p["CL"], p["Vc"], p["Q"], p["Vp"], doses)
}

fit_population_pk <- function(data, meta, start = NULL, ci_level = 0.95) {
  data <- validate_pk_data(data, meta, population = TRUE)
  required_columns(data, c("dose_mg", "dose_time_h", "duration_h"))
  if (!identical(meta$regimen_type, "single_dose"))
    pkpd_stop("Population prototype requires explicit metadata regimen_type='single_dose'.")
  assert_numeric(data$dose_mg, "dose_mg", positive = TRUE)
  assert_numeric(data$dose_time_h, "dose_time_h")
  assert_numeric(data$duration_h, "duration_h", nonnegative = TRUE)
  if (any(data$dose_time_h != 0) || any(data$duration_h != 0) || any(data$time_h < 0))
    pkpd_stop("Population prototype is one-compartment single IV bolus at time zero; other schedules require an extension.")
  if (any(data$concentration_mg_L <= 0)) pkpd_stop("Population lognormal fit requires positive concentrations.")
  groups <- split(data, data$subject_id)
  if (length(groups) < 3L || any(vapply(groups, nrow, integer(1)) < 3L))
    pkpd_stop("This random-effects prototype needs at least 3 subjects and 3 time points each; this is not a reliability sample-size criterion.")
  if (any(vapply(groups, function(g) length(unique(g$dose_mg)) != 1L, logical(1)))) pkpd_stop("dose_mg must be constant within subject for the single-dose model.")
  data$subject_id <- factor(data$subject_id)
  if (is.null(start)) {
    starts <- vapply(groups, function(g) {
      line <- stats::coef(stats::lm(log(concentration_mg_L) ~ time_h, data = g))
      v <- g$dose_mg[1] / exp(line[1]); cl <- max(1e-5, -line[2]) * v
      c(CL = unname(cl), V = unname(v))
    }, numeric(2))
    start <- exp(rowMeans(log(starts)))
  }
  if (!setequal(names(start), c("CL", "V"))) pkpd_stop("start requires CL and V.")
  assert_numeric(start, "start", positive = TRUE)
  captured <- capture_fit(nlme::nlme(log(concentration_mg_L) ~ log(dose_mg) - log_V - exp(log_CL - log_V) * time_h,
      data = data, fixed = log_CL + log_V ~ 1,
      random = nlme::pdDiag(log_CL + log_V ~ 1), groups = ~ subject_id,
      start = c(log_CL = log(start[["CL"]]), log_V = log(start[["V"]])), method = "ML",
      na.action = stats::na.fail, control = nlme::nlmeControl(maxIter = 150, pnlsMaxIter = 30, msMaxIter = 150, returnObject = FALSE)))
  fit <- captured$value
  beta <- nlme::fixef(fit)
  table <- parameter_table(beta, stats::vcov(fit), c(TRUE, TRUE), ci_level)
  table$unit <- c("L/h", "L")
  predicted <- as.numeric(exp(stats::predict(fit, level = 1)))
  structure(list(type = "population_pk", fit = fit, parameters = table,
                 covariance_log_parameters = stats::vcov(fit), meta = meta, data = data,
                 predicted = predicted, warnings = captured$warnings,
                 random_effects = nlme::ranef(fit), variance_components = as.data.frame(unclass(nlme::VarCorr(fit))),
                 diagnostics = c(fit_diagnostics(fit, data$concentration_mg_L, predicted, TRUE),
                                 list(n_subjects = length(groups), prediction_scale = "Conditional median for lognormal error",
                                      random_effect_structure = "Independent log-CL and log-V random effects"))),
            class = "pkpd_fit")
}

predict_population_pk <- function(object, newdata, individual = FALSE) {
  if (object$type != "population_pk") pkpd_stop("Not a population PK fit.")
  required_columns(newdata, c("time_h", "dose_mg"))
  assert_numeric(newdata$time_h, "time_h", nonnegative = TRUE)
  assert_numeric(newdata$dose_mg, "dose_mg", positive = TRUE)
  beta <- nlme::fixef(object$fit)
  log_cl <- rep(unname(beta["log_CL"]), nrow(newdata))
  log_v <- rep(unname(beta["log_V"]), nrow(newdata))
  if (individual) {
    required_columns(newdata, "subject_id")
    if (any(!as.character(newdata$subject_id) %in% as.character(object$data$subject_id)))
      pkpd_stop("Individual prediction requires a fitted subject; use population prediction for new subjects.")
    eta <- nlme::ranef(object$fit)
    selected <- match(as.character(newdata$subject_id), rownames(eta))
    log_cl <- log_cl + eta[selected, "log_CL"]
    log_v <- log_v + eta[selected, "log_V"]
  }
  # Evaluate the fitted structural equation directly. Some nlme versions collect
  # variables from log(response) and incorrectly require a response in newdata.
  as.numeric(newdata$dose_mg * exp(-log_v) * exp(-exp(log_cl - log_v) * newdata$time_h))
}

indices_from_pk_fit <- function(object, mic_mg_L, window_h, fu = NULL, output_basis = "free", step_h = 0.02) {
  if (object$type != "individual_pk") pkpd_stop("Use a specified individual PK model for schedule-aware indices.")
  assert_scalar(step_h, "step_h", positive = TRUE)
  assert_numeric(window_h, "window_h")
  if (length(window_h) != 2L || window_h[1] >= window_h[2]) pkpd_stop("Invalid window_h.")
  doses <- object$doses
  events <- unique(c(doses$time_h, doses$time_h + doses$duration_h))
  breaks <- sort(unique(c(window_h, events[events > window_h[1] & events < window_h[2]])))
  central_v <- if (object$compartments == 1L) object$theta[["V"]] else object$theta[["Vc"]]
  meta <- object$meta; meta$data_origin <- "model_prediction"; meta$record_level <- "model_prediction"
  segments <- list()
  for (i in seq_len(length(breaks) - 1L)) {
    left <- breaks[i]; right <- breaks[i + 1L]
    grid <- seq(left, right, length.out = max(2, ceiling((right - left) / step_h) + 1L))
    c <- predict_pk(object, grid)
    # Use the left limit at every segment's right boundary; the next segment
    # begins post-bolus. Thus no trapezoid ever crosses a concentration jump.
    at_end <- doses$duration_h == 0 & abs(doses$time_h - right) < 1e-12
    if (any(at_end)) c[length(c)] <- max(0, c[length(c)] - sum(doses$dose_mg[at_end]) / central_v)
    segments[[i]] <- pkpd_indices(grid, c, mic_mg_L, c(left, right), meta, output_basis, fu, method = "linear_up_log_down")
  }
  result <- segments[[1]]
  result$window_start_h <- window_h[1]; result$window_end_h <- window_h[2]
  result$window_duration_h <- unname(diff(window_h))
  result$AUC_mg_h_L <- sum(vapply(segments, `[[`, numeric(1), "AUC_mg_h_L"))
  result$Cmax_profile_mg_L <- max(vapply(segments, `[[`, numeric(1), "Cmax_profile_mg_L"))
  result$time_above_MIC_h <- sum(vapply(segments, `[[`, numeric(1), "time_above_MIC_h"))
  result$AUC_MIC_h <- result$AUC_mg_h_L / mic_mg_L
  result$Cmax_MIC <- result$Cmax_profile_mg_L / mic_mg_L
  result$percent_time_above_MIC <- 100 * result$time_above_MIC_h / diff(window_h)
  result$n_profile_points <- sum(vapply(segments, `[[`, numeric(1), "n_profile_points"))
  result$window_interpretation <- "Model-derived half-open window [start,end); right-boundary bolus excluded. Not automatically steady state."
  result$interpolation <- "Event-split model grid; linear-up/log-down within each continuous segment"
  result$integration_step_h <- step_h; result$n_continuous_segments <- length(segments)
  result$peak_interpretation <- "Model-grid maximum including post-bolus limits; refine step_h to check numerical sensitivity."
  result
}
