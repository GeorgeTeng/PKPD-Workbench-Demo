# Fully synthetic, generic drug and biomarker demonstration. No pathogen data.
script_arg <- grep("^--file=", commandArgs(), value = TRUE)[1]
script <- normalizePath(sub("^--file=", "", script_arg), mustWork = TRUE)
root <- dirname(dirname(script))
source(file.path(root, "load.R"), encoding = "UTF-8")
args <- commandArgs(trailingOnly = TRUE)
out <- if (length(args)) args[1] else file.path(root, "outputs", "demo")
if (dir.exists(out) && length(list.files(out, all.files = TRUE, no.. = TRUE))) stop("Use a new output directory; previous runs are preserved.")
dir.create(out, recursive = TRUE, showWarnings = FALSE)
set.seed(16092026)
meta <- list(drug = "SyntheticDrug", species = "synthetic_animal", matrix = "plasma",
             concentration_unit = "mg/L", time_unit = "h", dose_unit = "mg", route = "IV",
             concentration_basis = "total", record_level = "individual", data_origin = "synthetic",
             regimen_type = "single_dose")
doses <- data.frame(time_h = 0, dose_mg = 100, duration_h = 0)
times <- c(0.1, 0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 18, 24)
individual <- data.frame(subject_id = "demo_individual", time_h = times,
                         concentration_mg_L = pk_1cpt(times, 2, 12, doses) * exp(rnorm(length(times), 0, 0.025)))
fit_one <- fit_pk_individual(individual, doses, meta)
export_pkpd_fit(fit_one, file.path(out, "individual_pk"))

two_data <- data.frame(subject_id = "demo_two", time_h = times,
                       concentration_mg_L = pk_2cpt(times, 2, 8, 3, 16, doses) * exp(rnorm(length(times), 0, 0.008)))
fit_two <- fit_pk_individual(two_data, doses, meta, compartments = 2,
                             start = c(CL = 1.8, Vc = 9, Q = 2.5, Vp = 15))
export_pkpd_fit(fit_two, file.path(out, "two_compartment_pk"))

n_subjects <- 24L
truth <- data.frame(subject_id = sprintf("S%02d", seq_len(n_subjects)),
                    CL = 2 * exp(rnorm(n_subjects, 0, 0.16)), V = 12 * exp(rnorm(n_subjects, 0, 0.12)))
population <- do.call(rbind, lapply(seq_len(n_subjects), function(i) {
  data.frame(subject_id = truth$subject_id[i], time_h = times, dose_mg = 100, dose_time_h = 0, duration_h = 0,
             concentration_mg_L = pk_1cpt(times, truth$CL[i], truth$V[i], doses) * exp(rnorm(length(times), 0, 0.06)))
}))
fit_pop <- fit_population_pk(population, meta)
export_pkpd_fit(fit_pop, file.path(out, "population_pk"))
utils::write.csv(truth, file.path(out, "synthetic_individual_truth.csv"), row.names = FALSE)

indices <- indices_from_pk_fit(fit_one, mic_mg_L = 1, window_h = c(0, 24), fu = 0.6)
write_pkpd_json(indices, file.path(out, "pkpd_indices.json"))

# Use generated PK profiles with distinct schedules solely to exercise candidate
# indices. Endpoints below are an artificial response, not microbial measurements.
endpoint <- do.call(rbind, lapply(seq_len(72L), function(i) {
  total <- exp(runif(1, log(10), log(350)))
  interval <- c(6, 12, 24)[(i - 1L) %% 3L + 1L]
  cl <- exp(runif(1, log(1), log(4))); v <- exp(runif(1, log(8), log(20)))
  d <- data.frame(time_h = seq(0, 24 - interval, by = interval), dose_mg = total / (24 / interval), duration_h = 0)
  object <- fit_one; object$theta <- c(CL = cl, V = v); object$doses <- d
  index <- indices_from_pk_fit(object, 1, c(0, 24), fu = 0.6, step_h = 0.05)
  data.frame(unit_id = sprintf("U%03d", i), study_id = paste0("batch", (i - 1L) %% 6L + 1L),
             fAUC_MIC_h = index$AUC_MIC_h, fCmax_MIC = index$Cmax_MIC,
             fT_MIC_percent = index$percent_time_above_MIC,
             response = emax_response(index$AUC_MIC_h, E0 = 8, Emax = 5, EC50 = 20, direction = "decreasing") + rnorm(1, 0, 0.16))
}))
comparison <- compare_pkpd_indices(endpoint, c("fAUC_MIC_h", "fCmax_MIC", "fT_MIC_percent"), group_col = "study_id")
utils::write.csv(endpoint, file.path(out, "synthetic_endpoint_data.csv"), row.names = FALSE)
utils::write.csv(comparison$comparison, file.path(out, "index_comparison.csv"), row.names = FALSE)
write_pkpd_json(comparison[c("comparison", "fold_results", "index_correlation", "interpretation")], file.path(out, "index_comparison.json"))
synthetic_provenance <- list(data_origin = "synthetic", source = "scripts/run_demo.R", seed = 16092026L)
for (name in names(comparison$models)) export_pkpd_fit(comparison$models[[name]], file.path(out, "endpoint", name), synthetic_provenance)

response_data <- do.call(rbind, lapply(seq_len(24), function(i) {
  t <- seq(0, 12, by = 1.5)
  exposure <- runif(1, 0.5, 3) * exp(-0.05 * t)
  b <- rnorm(1, 0, 0.5)
  data.frame(subject_id = paste0("R", i), time_h = t, exposure = exposure,
             response = 10 + 0.3 * t - 0.018 * t^2 - 1.2 * exposure + b + rnorm(length(t), 0, 0.2))
}))
fit_response <- fit_response_longitudinal(response_data, response_unit = "arbitrary biomarker units", spline_df = 3)
export_pkpd_fit(fit_response, file.path(out, "longitudinal_response"), synthetic_provenance)

png(file.path(out, "synthetic_demo.png"), width = 1600, height = 1000, res = 150)
par(mfrow = c(2, 2), mar = c(4, 4, 2.8, 1), oma = c(1.5, 0, 1, 0), cex = 0.9)
grid <- seq(0, 24, length.out = 400)
plot(individual$time_h, individual$concentration_mg_L, pch = 16, col = "#246A73", xlab = "Time (h)", ylab = "Concentration (mg/L)", main = "Individual PK: synthetic observations")
lines(grid, predict_pk(fit_one, grid), col = "#CC5C2C", lwd = 2)
legend("topright", c("Synthetic observations", "Fitted one-compartment curve"), col = c("#246A73", "#CC5C2C"), pch = c(16, NA), lty = c(NA, 1), bty = "n", cex = 0.8)
plot(fit_pop$predicted, fit_pop$data$concentration_mg_L, pch = 16, col = "#246A7380", xlab = "Individual predicted concentration (mg/L)", ylab = "Observed concentration (mg/L)", main = "Repeated-measure population PK")
abline(0, 1, col = "#CC5C2C", lwd = 2)
emax <- comparison$models$fAUC_MIC_h
plot(endpoint$fAUC_MIC_h, endpoint$response, pch = 16, col = "#246A7380", xlab = "Free AUC / MIC (h)", ylab = "Generic response (arbitrary units)", main = "Endpoint Emax regression")
x <- seq(0, max(endpoint$fAUC_MIC_h), length.out = 400)
lines(x, predict_emax(emax, x), col = "#CC5C2C", lwd = 2)
plot(fit_response$predicted, fit_response$data$response, pch = 16, col = "#246A7380", xlab = "Predicted generic response", ylab = "Observed generic response", main = "Optional longitudinal response regression")
abline(0, 1, col = "#CC5C2C", lwd = 2)
mtext("SYNTHETIC DEMONSTRATION - no real drug, pathogen, animal or human validation data", outer = TRUE, side = 1, cex = 0.75)
dev.off()

manifest <- list(schema_version = "0.1", software_version = PKPD_VERSION, data_origin = "synthetic",
                 input_context_rule = "Original compact context is unchanged; numerical results use a separate analysis manifest.",
                 human_pk_used = FALSE, pbpk_used = FALSE,
                 analyses = c("PKPD indices", "one- and two-compartment individual PK", "one-compartment population PK", "endpoint Emax", "grouped index comparison", "longitudinal generic response"),
                 missing_information = "NOT_FOUND denotes unavailable descriptive information; uncomputed numeric outputs are JSON null with status/reason.",
                 reliability = "Parameter recovery and software tests only; not a validation of a real drug model.",
                 review = "PENDING_HUMAN_REVIEW", created_at = format(Sys.time(), tz = "UTC", usetz = TRUE))
write_pkpd_json(manifest, file.path(out, "analysis_manifest.json"))
write_pkpd_json(list(individual_one = list(truth = c(CL = 2, V = 12), fitted = fit_one$theta),
                     individual_two = list(truth = c(CL = 2, Vc = 8, Q = 3, Vp = 16), fitted = fit_two$theta),
                     population = list(generating_typical = c(CL = 2, V = 12), fitted = fit_pop$parameters),
                     endpoint = list(truth = c(E0 = 8, Emax = 5, EC50 = 20), fitted = emax$theta)),
                  file.path(out, "parameter_recovery.json"))
writeLines(capture.output(sessionInfo()), file.path(out, "session_info.txt"))
cat("Demo completed:", normalizePath(out), "\n")
print(comparison$comparison)
