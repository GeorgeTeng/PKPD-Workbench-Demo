# Generic Emax/Hill endpoint model. One independently measured endpoint per unit.
emax_response <- function(index, E0, Emax, EC50, hill = 1, direction = "decreasing") {
  assert_numeric(index, "index", nonnegative = TRUE)
  assert_scalar(E0, "E0"); assert_scalar(Emax, "Emax", positive = TRUE)
  assert_scalar(EC50, "EC50", positive = TRUE); assert_scalar(hill, "hill", positive = TRUE)
  if (!direction %in% c("increasing", "decreasing")) pkpd_stop("Choose increasing or decreasing response.")
  sign <- if (direction == "decreasing") -1 else 1
  fraction <- ifelse(index == 0, 0, stats::plogis(hill * (log(pmax(index, .Machine$double.xmin)) - log(EC50))))
  E0 + sign * Emax * fraction
}

fit_index_emax <- function(data, index_col, response_col = "response", id_col = "unit_id",
                            direction = "decreasing", estimate_hill = FALSE,
                            ci_level = 0.95, sparse_exploratory = FALSE) {
  required_columns(data, c(index_col, response_col, id_col))
  check_blq(data)
  if (anyNA(data[[id_col]]) || anyDuplicated(data[[id_col]]))
    pkpd_stop("Endpoint fitting requires one independent endpoint per unit; use a longitudinal model for repeated outcomes.")
  x <- data[[index_col]]; y <- data[[response_col]]
  assert_numeric(x, index_col, nonnegative = TRUE); assert_numeric(y, response_col)
  if (!direction %in% c("increasing", "decreasing")) pkpd_stop("Unknown response direction.")
  npar <- if (estimate_hill) 4L else 3L
  if (!is.logical(sparse_exploratory) || length(sparse_exploratory) != 1L || is.na(sparse_exploratory))
    pkpd_stop("sparse_exploratory must be TRUE or FALSE.")
  # The standard pipeline keeps >=3 residual degrees of freedom. A separately
  # declared descriptive review may use 2; this does not establish adequacy.
  min_df <- if (sparse_exploratory) 2L else 3L
  if (length(x) - npar < min_df || length(unique(x)) < npar + 1L)
    pkpd_stop("Insufficient exposure support for this Emax model; do not equate row count with identifiability.")
  if (diff(range(y)) <= 1e-10) pkpd_stop("Constant response does not identify Emax and EC50.")
  working <- data.frame(x = x, y = y)
  sign <- if (direction == "decreasing") -1 else 1
  f <- if (estimate_hill) y ~ E0 + sign * exp(log_Emax) * plogis(exp(log_hill) * (log(x) - log_EC50)) else
    y ~ E0 + sign * exp(log_Emax) * plogis(log(x) - log_EC50)
  # log(0)=-Inf, plogis(-Inf)=0: zero exposure is a defined baseline, not omitted.
  scale_x <- stats::median(x[x > 0])
  scale_y <- diff(range(y))
  baseline <- mean(y[x == min(x)])
  candidates <- list(); failures <- character()
  for (ec in scale_x * c(0.25, 1, 4)) {
    for (effect in scale_y * c(1, 2)) {
      initial <- list(E0 = baseline, log_Emax = log(effect), log_EC50 = log(ec))
      if (estimate_hill) initial$log_hill <- 0
      lower <- c(E0 = -Inf, log_Emax = log(scale_y) - 12, log_EC50 = log(min(x[x > 0])) - 12)
      upper <- c(E0 = Inf, log_Emax = log(scale_y) + 12, log_EC50 = log(max(x)) + 12)
      if (estimate_hill) { lower <- c(lower, log_hill = log(0.05)); upper <- c(upper, log_hill = log(20)) }
      attempt <- tryCatch(capture_fit(minpack.lm::nlsLM(f, data = working, start = initial,
                            lower = lower, upper = upper,
                            control = minpack.lm::nls.lm.control(maxiter = 400), model = TRUE)), error = identity)
      if (inherits(attempt, "error")) failures <- c(failures, conditionMessage(attempt)) else
        if (isTRUE(attempt$value$convInfo$isConv)) candidates[[length(candidates) + 1L]] <- attempt
    }
  }
  if (!length(candidates)) pkpd_stop("Emax fit failed: ", paste(unique(failures), collapse = "; "))
  best <- candidates[[which.min(vapply(candidates, function(a) stats::deviance(a$value), numeric(1)))]]
  fit <- best$value; beta <- stats::coef(fit)
  covariance <- tryCatch(stats::vcov(fit), error = function(e) NULL)
  if (is.null(covariance)) pkpd_stop("Emax fit lacks parameter covariance; inspect exposure range and identifiability.")
  parameters <- parameter_table(beta, covariance, names(beta) != "E0", ci_level, stats::df.residual(fit))
  theta <- c(E0 = beta[["E0"]], Emax = exp(beta[["log_Emax"]]), EC50 = exp(beta[["log_EC50"]]),
             hill = if (estimate_hill) exp(beta[["log_hill"]]) else 1)
  predicted <- emax_response(x, theta["E0"], theta["Emax"], theta["EC50"], theta["hill"], direction)
  flags <- best$warnings
  if (sparse_exploratory) flags <- c(flags,
    "Sparse exploratory fit only; no adequacy approval. AICc is unavailable when n <= k+1, with k including residual variance.")
  if (theta["EC50"] < min(x[x > 0]) || theta["EC50"] > max(x)) flags <- c(flags, "EC50 lies outside observed positive exposure range.")
  if (estimate_hill && (theta["hill"] < 0.051 || theta["hill"] > 19.9)) flags <- c(flags, "Hill estimate approaches imposed numerical bound.")
  structure(list(type = "endpoint_emax", fit = fit, parameters = parameters, theta = theta,
                 covariance_parameters = covariance, data = data, predicted = predicted,
                 index_col = index_col, response_col = response_col, id_col = id_col,
                 direction = direction, estimate_hill = estimate_hill, warnings = flags,
                 sparse_exploratory = sparse_exploratory,
                 diagnostics = c(fit_diagnostics(fit, y, predicted),
                                 list(n_independent_units = nrow(data), starts_converged = length(candidates),
                                      model = "Independent Gaussian endpoint errors; index measurement error not modeled"))),
            class = "pkpd_fit")
}

predict_emax <- function(object, index) {
  if (object$type != "endpoint_emax") pkpd_stop("Not an endpoint Emax model.")
  p <- object$theta
  emax_response(index, p["E0"], p["Emax"], p["EC50"], p["hill"], object$direction)
}

compare_pkpd_indices <- function(data, index_columns, response_col = "response", id_col = "unit_id",
                                 group_col = NULL, direction = "decreasing", estimate_hill = FALSE) {
  required_columns(data, c(index_columns, response_col, id_col))
  if (length(index_columns) < 2L) pkpd_stop("Supply at least two candidate indices.")
  if (anyNA(data[c(index_columns, response_col, id_col)])) pkpd_stop("Comparison must use the same complete observations for all indices.")
  if (!is.null(group_col)) {
    required_columns(data, group_col)
    if (anyNA(data[[group_col]]) || length(unique(data[[group_col]])) < 3L)
      pkpd_stop("Grouped external-to-fit checks need at least three declared groups.")
  }
  models <- list(); rows <- list(); folds <- list()
  for (name in index_columns) {
    fit <- tryCatch(fit_index_emax(data, name, response_col, id_col, direction, estimate_hill), error = identity)
    if (inherits(fit, "error")) {
      rows[[name]] <- data.frame(index = name, status = "FIT_FAILED", AIC = NA_real_, AICc = NA_real_,
                                 BIC = NA_real_, log_likelihood = NA_real_, n_parameters = NA_real_, n_observations = nrow(data),
                                 training_RMSE = NA_real_, grouped_CV_RMSE = NA_real_,
                                 folds_successful = 0L, folds_total = if (is.null(group_col)) 0L else length(unique(data[[group_col]])),
                                 reason = conditionMessage(fit))
      next
    }
    models[[name]] <- fit
    errors <- numeric(); success <- 0L; total <- 0L
    if (!is.null(group_col)) {
      for (group in unique(as.character(data[[group_col]]))) {
        total <- total + 1L
        heldout <- as.character(data[[group_col]]) == group
        trial <- tryCatch(fit_index_emax(data[!heldout, , drop = FALSE], name, response_col, id_col, direction, estimate_hill), error = identity)
        key <- paste(name, group, sep = "::")
        if (inherits(trial, "error")) {
          folds[[key]] <- list(index = name, heldout_group = group, status = "FAILED", reason = conditionMessage(trial))
        } else {
          pred <- predict_emax(trial, data[[name]][heldout])
          errors <- c(errors, data[[response_col]][heldout] - pred)
          success <- success + 1L
          folds[[key]] <- list(index = name, heldout_group = group, status = "FITTED",
                              n_test = sum(heldout), RMSE = sqrt(mean((data[[response_col]][heldout] - pred)^2)))
        }
      }
    }
    # Do not rank by an optimistically selected subset of successful folds.
    cv <- if (total > 0L && success == total) sqrt(mean(errors^2)) else NA_real_
    rows[[name]] <- data.frame(index = name, status = "FITTED", AIC = fit$diagnostics$AIC, AICc = fit$diagnostics$AICc,
                               BIC = fit$diagnostics$BIC, log_likelihood = fit$diagnostics$log_likelihood,
                               n_parameters = fit$diagnostics$n_parameters, n_observations = fit$diagnostics$n_observations,
                               training_RMSE = fit$diagnostics$RMSE_original_scale, grouped_CV_RMSE = cv,
                               folds_successful = success, folds_total = total, reason = paste(fit$warnings, collapse = "; "))
  }
  comparison <- do.call(rbind, rows); rownames(comparison) <- NULL
  list(comparison = comparison, models = models, fold_results = folds,
       index_correlation = suppressWarnings(stats::cor(data[index_columns])),
       interpretation = "Same endpoint and observations; grouped CV withholds entire declared groups. Correlated indices cannot be distinguished reliably by fit alone.")
}
