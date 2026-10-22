# Integrals and threshold crossings are consistent with the selected interpolation.
segment_value <- function(c0, c1, fraction, log_down) {
  if (log_down) exp(log(c0) + fraction * (log(c1) - log(c0))) else c0 + fraction * (c1 - c0)
}

segment_auc <- function(c0, c1, dt, log_down) {
  if (log_down && abs(log(c1 / c0)) > 1e-10) dt * (c1 - c0) / log(c1 / c0)
  else dt * (c0 + c1) / 2
}

segment_time_above <- function(c0, c1, dt, threshold, log_down) {
  if (c0 > threshold && c1 > threshold) return(dt)
  if (c0 <= threshold && c1 <= threshold) return(0)
  fraction <- if (log_down) log(threshold / c0) / log(c1 / c0) else (threshold - c0) / (c1 - c0)
  fraction <- min(1, max(0, fraction))
  if (c0 > threshold) dt * fraction else dt * (1 - fraction)
}

pkpd_indices <- function(time_h, concentration_mg_L, mic_mg_L, window_h, meta,
                         output_basis = "free", fu = NULL,
                         method = c("linear", "linear_up_log_down"),
                         discontinuities_h = numeric()) {
  validate_meta(meta)
  method <- match.arg(method)
  assert_numeric(time_h, "time_h")
  assert_numeric(concentration_mg_L, "concentration_mg_L", nonnegative = TRUE)
  assert_scalar(mic_mg_L, "mic_mg_L", positive = TRUE)
  assert_numeric(window_h, "window_h")
  if (length(time_h) != length(concentration_mg_L) || length(time_h) < 2) pkpd_stop("A profile needs at least two paired time/concentration values.")
  if (length(window_h) != 2 || window_h[1] >= window_h[2]) pkpd_stop("Supply an increasing two-endpoint window_h.")
  if (!output_basis %in% c("free", "total")) pkpd_stop("output_basis must be free or total.")
  if (anyDuplicated(time_h)) pkpd_stop("Duplicate times may represent a bolus jump; split continuous profiles explicitly.")
  ordering <- order(time_h)
  time_h <- time_h[ordering]
  concentration_mg_L <- concentration_mg_L[ordering]
  if (window_h[1] < min(time_h) || window_h[2] > max(time_h))
    pkpd_stop("Requested window is not covered; no concentration extrapolation or automatic 24-h scaling.")
  if (length(discontinuities_h)) {
    assert_numeric(discontinuities_h, "discontinuities_h")
    if (any(discontinuities_h > window_h[1] & discontinuities_h < window_h[2]))
      pkpd_stop("Window crosses a declared concentration discontinuity; calculate continuous segments separately.")
  }
  conversion <- "none"
  if (meta$concentration_basis == output_basis) {
    if (!is.null(fu)) pkpd_stop("Do not apply fu when input and output basis already match.")
  } else if (meta$concentration_basis == "total" && output_basis == "free") {
    assert_scalar(fu, "fu", positive = TRUE)
    if (fu > 1) pkpd_stop("fu must be <= 1.")
    concentration_mg_L <- concentration_mg_L * fu
    conversion <- "constant fu applied to total concentration"
  } else pkpd_stop("Free-to-total back-calculation is not implicit; supply an explicit total profile.")
  auc <- t_above <- 0
  candidates <- numeric()
  for (i in seq_len(length(time_h) - 1L)) {
    left <- max(time_h[i], window_h[1]); right <- min(time_h[i + 1L], window_h[2])
    if (left >= right) next
    c0 <- concentration_mg_L[i]; c1 <- concentration_mg_L[i + 1L]
    log_down <- method == "linear_up_log_down" && c0 > c1 && c1 > 0
    dt <- time_h[i + 1L] - time_h[i]
    ca <- segment_value(c0, c1, (left - time_h[i]) / dt, log_down)
    cb <- segment_value(c0, c1, (right - time_h[i]) / dt, log_down)
    auc <- auc + segment_auc(ca, cb, right - left, log_down)
    t_above <- t_above + segment_time_above(ca, cb, right - left, mic_mg_L, log_down)
    candidates <- c(candidates, ca, cb)
  }
  duration <- diff(window_h)
  list(window_start_h = window_h[1], window_end_h = window_h[2], window_duration_h = unname(duration),
       AUC_mg_h_L = auc, Cmax_profile_mg_L = max(candidates), MIC_mg_L = mic_mg_L,
       AUC_MIC_h = auc / mic_mg_L, Cmax_MIC = max(candidates) / mic_mg_L,
       time_above_MIC_h = t_above, percent_time_above_MIC = 100 * t_above / duration,
       input_basis = meta$concentration_basis, output_basis = output_basis, fu = fu,
       conversion = conversion, interpolation = method, n_profile_points = length(time_h),
       peak_interpretation = "Maximum of supplied/interpolated profile; a sparsely sampled peak may be missed.",
       window_interpretation = "Finite supplied window; not automatically steady state or 24 hours.",
       data_origin = meta$data_origin)
}

