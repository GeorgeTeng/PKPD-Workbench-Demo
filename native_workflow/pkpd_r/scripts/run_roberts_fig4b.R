# Reproducible analysis of the requested Fig. 4b worksheet only.
script <- normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[1]), mustWork = TRUE)
source(file.path(dirname(dirname(script)), "load.R"), encoding = "UTF-8")
args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args)) args[1] else "outputs/Roberts_2022_Fig4b_2026-09-16"
out <- if (length(args) >= 2) args[2] else file.path(root, "results")
if (dir.exists(out) && length(list.files(out))) stop("Results already exist; preserve the previous run.")
dir.create(out, recursive = TRUE, showWarnings = FALSE)
all <- read.csv(file.path(root, "inputs/source_records.csv"), fileEncoding = "UTF-8-BOM", stringsAsFactors = FALSE)
data <- subset(all, status == "QUANTIFIED")
stopifnot(nrow(data) == 147, length(unique(data$subject_id)) == 16, !anyNA(data$concentration_mg_L))
data$dose_time_h <- 0
source_manifest <- jsonlite::read_json(file.path(root, "inputs/source_manifest.json"), simplifyVector = TRUE)
provenance <- list(data_origin = "observed", source = source_manifest$source_file, source_sha256 = source_manifest$source_sha256,
                  sheet = "Fig. 4b", doi = source_manifest$doi,
                  preprocessing = "Quantifiable-only exploratory analysis. 4 BLQ records, 5 unavailable blood samples and 4 unsampled times retained separately; no imputation.",
                  numerical_LLOQ_mg_L = "NOT_FOUND")
base_meta <- list(drug = "PMB", species = "Sprague-Dawley rat", matrix = "plasma",
                 concentration_unit = "mg/L", time_unit = "h", dose_unit = "mg/kg", route = "IV",
                 concentration_basis = "total", record_level = "individual", data_origin = "observed",
                 regimen_type = "single_dose", infusion_duration_h = 1/60,
                 individual_weight_kg = "NOT_FOUND", dose_time_origin = "Assumed infusion start at t=0; duration 1 min from article methods.")
doses <- data.frame(time_h = 0, dose_mg_kg = 1, duration_h = 1/60)
individual_fits <- list(); comparisons <- list(); parameter_rows <- list(); failures <- list()
for (id in unique(data$subject_id)) {
  d <- data[data$subject_id == id, ]; meta <- base_meta; meta$drug <- d$drug[1]
  one <- fit_pk_per_kg(d, doses, meta)
  individual_fits[[paste(id, "1cpt", sep = "_")]] <- one
  two <- list()
  starts <- expand.grid(v_fraction = c(0.1, 0.3, 0.7), q_fraction = c(0.5, 2, 5), vp_fraction = c(0.5, 2))
  for (j in seq_len(nrow(starts))) {
    start <- c(CL = unname(one$theta["CL"]), Vc = unname(one$theta["V"]) * starts$v_fraction[j],
               Q = unname(one$theta["CL"]) * starts$q_fraction[j], Vp = unname(one$theta["V"]) * starts$vp_fraction[j])
    attempt <- tryCatch(fit_pk_per_kg(d, doses, meta, compartments = 2, start = start), error = identity)
    if (!inherits(attempt, "error")) two[[length(two) + 1L]] <- attempt
    else failures[[paste(id, j, sep = "_")]] <- conditionMessage(attempt)
  }
  if (length(two)) individual_fits[[paste(id, "2cpt", sep = "_")]] <- two[[which.min(vapply(two, function(x) x$diagnostics$AIC, numeric(1)))]]
  for (comp in 1:2) {
    key <- paste(id, paste0(comp, "cpt"), sep = "_"); fit <- individual_fits[[key]]
    if (is.null(fit)) next
    p <- fit$parameters
    parameter_rows[[key]] <- cbind(drug = d$drug[1], subject_id = id, compartments = comp, p)
    comparisons[[key]] <- data.frame(drug = d$drug[1], subject_id = id, compartments = comp, n = nrow(d),
      AIC = fit$diagnostics$AIC, AICc = fit$diagnostics$AICc, log_RMSE = fit$diagnostics$RMSE_on_fit_scale,
      max_RSE_percent = max(p$RSE_percent), covariance_condition = kappa(fit$covariance_log_parameters),
      all_CI_finite = all(is.finite(p$CI_lower) & is.finite(p$CI_upper)),
      starts_converged = if (comp == 1) 1 else length(two),
      warning = paste(fit$warnings, collapse = "; "))
    export_pkpd_fit(fit, file.path(out, "individual", key), provenance)
  }
}
comparison <- do.call(rbind, comparisons); rownames(comparison) <- NULL
comparison$delta_AICc <- ave(comparison$AICc, comparison$subject_id, FUN = function(x) x - min(x))
parameters <- do.call(rbind, parameter_rows); rownames(parameters) <- NULL
write.csv(comparison, file.path(out, "individual_model_comparison.csv"), row.names = FALSE)
write.csv(parameters, file.path(out, "individual_parameters.csv"), row.names = FALSE)
write_pkpd_json(failures, file.path(out, "multistart_failures.json"))

population_fits <- list(); group_parameters <- list(); exposure_rows <- list(); predictions <- list()
for (drug in unique(data$drug)) {
  d <- data[data$drug == drug, ]; meta <- base_meta; meta$drug <- drug
  ids <- unique(d$subject_id)
  theta <- vapply(ids, function(id) individual_fits[[paste0(id, "_1cpt")]]$theta, numeric(2))
  start <- exp(rowMeans(log(theta)))
  fit <- fit_population_pk_infusion_per_kg(d, meta, start)
  population_fits[[drug]] <- fit
  export_pkpd_fit(fit, file.path(out, "population", drug), provenance)
  group_parameters[[drug]] <- cbind(drug = drug, fit$parameters)
  p <- setNames(fit$parameters$estimate, fit$parameters$parameter)
  predict_typical <- function(t) predict_population_pk_infusion_per_kg(fit,
      data.frame(time_h = t, dose_mg_kg = 1, dose_time_h = 0, duration_h = 1/60))
  auc06 <- integrate(predict_typical, 0, 1/60)$value + integrate(predict_typical, 1/60, 6)$value
  exposure_rows[[drug]] <- data.frame(drug = drug, model = "population_one_compartment_single_infusion",
      n_rats = length(ids), n_quantified = nrow(d), CL_L_h_kg = p["CL"], V_L_kg = p["V"],
      half_life_h = log(2) * p["V"] / p["CL"], AUC_0_6_mg_h_L = auc06,
      AUC_0_inf_mg_h_L = 1/p["CL"], model_Cmax_mg_L = predict_typical(1/60),
      Cmax_interpretation = "Extrapolated infusion-end peak before first sample; sensitive to compartment structure")
  d$predicted_individual <- predict_population_pk_infusion_per_kg(fit, d, TRUE)
  d$predicted_typical <- predict_population_pk_infusion_per_kg(fit, d)
  d$log_residual <- log(d$concentration_mg_L / d$predicted_individual)
  predictions[[drug]] <- d
  stopifnot(max(abs(d$predicted_individual - fit$predicted)) < 1e-7)
}
pop_parameters <- do.call(rbind, group_parameters); rownames(pop_parameters) <- NULL
exposures <- do.call(rbind, exposure_rows); rownames(exposures) <- NULL
pred <- do.call(rbind, predictions); rownames(pred) <- NULL
write.csv(pop_parameters, file.path(out, "population_parameters.csv"), row.names = FALSE)
write.csv(exposures, file.path(out, "population_exposure.csv"), row.names = FALSE)
write.csv(pred, file.path(out, "population_predictions.csv"), row.names = FALSE)
write_pkpd_json(list(parameters = pop_parameters, exposure = exposures,
  individual_model_comparison = comparison, provenance = provenance), file.path(out, "results.json"))

# A common fully observed concentration window avoids extrapolating BLQ values.
# Five missing collection points remain explicit; interpolation bridges the
# observed neighbors and is labeled as a partial profile calculation.
profile_auc <- do.call(rbind, lapply(split(data, data$subject_id), function(d) {
  meta <- base_meta; meta$drug <- d$drug[1]
  # All subjects have coverage of 0.5-4 h. This deliberately is not AUC0-inf.
  t <- d$time_h; c <- d$concentration_mg_L
  ordering <- order(t); t <- t[ordering]; c <- c[ordering]
  stopifnot(min(t) <= 0.5, max(t) >= 4)
  auc <- 0
  for (j in seq_len(length(t)-1L)) {
    left <- max(0.5, t[j]); right <- min(4, t[j+1L])
    if (left >= right) next
    log_down <- c[j] > c[j+1L] && c[j+1L] > 0
    ca <- segment_value(c[j], c[j+1L], (left-t[j])/(t[j+1L]-t[j]), log_down)
    cb <- segment_value(c[j], c[j+1L], (right-t[j])/(t[j+1L]-t[j]), log_down)
    auc <- auc + segment_auc(ca, cb, right-left, log_down)
  }
  data.frame(drug = d$drug[1], subject_id = d$subject_id[1],
    window_start_h = 0.5, window_end_h = 4, AUC_mg_h_L = auc,
    note = "Partial observed-profile AUC with linear-up/log-down interpolation. No MIC supplied or needed for AUC alone.")
}))
write.csv(profile_auc, file.path(out, "observed_partial_AUC.csv"), row.names = FALSE)

colors <- c(PMB = "#235B8A", "FADDI-365" = "#B34C26")
png(file.path(out, "population_fit.png"), 1800, 1300, res = 160)
par(mfrow = c(2, 2), mar = c(4, 4.4, 3, 1), oma = c(2, 0, 1, 0))
for (drug in unique(data$drug)) {
  d <- pred[pred$drug == drug, ]; fit <- population_fits[[drug]]
  plot(d$time_h, d$concentration_mg_L, log = "y", pch = 16, col = adjustcolor(colors[drug], 0.55),
       xlab = "Time (h)", ylab = "Total plasma concentration (mg/L)", main = paste(drug, "- population 1-compartment"), xlim = c(0, 6))
  grid <- seq(0.02, 6, length.out = 300)
  for (id in unique(d$subject_id)) {
    nd <- data.frame(subject_id = id, time_h = grid, dose_mg_kg = 1, dose_time_h = 0, duration_h = 1/60)
    lines(grid, predict_population_pk_infusion_per_kg(fit, nd, TRUE), col = adjustcolor(colors[drug], 0.2))
  }
  lines(grid, predict_population_pk_infusion_per_kg(fit, nd), col = colors[drug], lwd = 2.5)
  legend("topright", c("Quantified observations", "Typical curve", "Individual curves"), pch = c(16, NA, NA),
         lty = c(NA, 1, 1), lwd = c(NA, 2.5, 1), col = c(colors[drug], colors[drug], adjustcolor(colors[drug], 0.3)), bty = "n", cex = 0.85)
}
for (drug in unique(data$drug)) {
  d <- pred[pred$drug == drug, ]
  plot(d$time_h, d$log_residual, pch = 16, col = adjustcolor(colors[drug], 0.65),
       xlab = "Time (h)", ylab = "log(observed / individual predicted)", main = paste(drug, "- residual pattern"))
  abline(h = 0, lty = 2, col = "gray40")
  at <- aggregate(log_residual ~ time_h, data = d, FUN = mean)
  lines(at$time_h, at$log_residual, col = colors[drug], lwd = 2)
}
mtext("Roberts 2022 Fig. 4b | 1 mg/kg IV over 1 min | Quantifiable-only fit; BLQ values retained separately", side = 1, outer = TRUE, cex = 0.85)
dev.off()

for (drug in unique(data$drug)) {
  ids <- unique(data$subject_id[data$drug == drug]); nrows <- ceiling(length(ids)/3)
  png(file.path(out, paste0(drug, "_individual_models.png")), 1900, max(1050, nrows * 490), res = 160)
  par(mfrow = c(nrows, 3), mar = c(4.5, 4.5, 2.5, 0.8), oma = c(2.5, 0, 1, 0), mgp = c(2.6, 0.7, 0), cex = 0.9)
  for (id in ids) {
    d <- data[data$subject_id == id, ]; grid <- seq(0.17, 6, length.out = 250)
    plot(d$time_h, d$concentration_mg_L, log = "y", pch = 16, col = "#313B44", xlab = "Time (h)", ylab = "Concentration (mg/L)", main = id, xlim = c(0, 6))
    lines(grid, predict_pk(individual_fits[[paste0(id, "_1cpt")]], grid), col = "#235B8A", lwd = 2)
    two <- individual_fits[[paste0(id, "_2cpt")]]
    if (!is.null(two)) lines(grid, predict_pk(two, grid), col = "#B34C26", lwd = 2, lty = 2)
    legend("topright", c("1 compartment", "2 compartments"), lty = c(1, 2), col = c("#235B8A", "#B34C26"), bty = "n", cex = 0.7)
  }
  mtext("Observed concentrations and separate individual fits; no BLQ imputation; 2-compartment convergence does not prove identifiability", side = 1, outer = TRUE, cex = 0.75)
  dev.off()
}
saveRDS(list(population = population_fits, individual = individual_fits), file.path(out, "all_models.rds"))
write_pkpd_json(list(software_version = PKPD_VERSION, source = source_manifest, analyses = c("Individual 1/2 compartment", "Population 1-compartment finite infusion", "Partial observed-profile AUC"),
  missing = list(MIC = "NOT_FOUND", numeric_LLOQ = "NOT_FOUND", individual_weight = "NOT_FOUND", PD_endpoint = "NOT_FOUND"),
  limitations = c("Quantifiable-only analysis can bias terminal PK; numeric LLOQ is unavailable for censored likelihood.",
    "Postdose sampling time is treated as from infusion start; the original rounded times are preserved.",
    "One-compartment population model is a baseline; inspect early-time residuals and two-compartment identifiability.",
    "No efficacy regression, PK/PD target, human scaling, or human prediction is estimated."),
  review = "PENDING_HUMAN_REVIEW"), file.path(out, "analysis_manifest.json"))
writeLines(capture.output(sessionInfo()), file.path(out, "session_info.txt"))
cat("Completed", normalizePath(out), "\n")
print(pop_parameters)
print(exposures)
print(comparison[, c("subject_id", "compartments", "AICc", "max_RSE_percent", "delta_AICc")])
