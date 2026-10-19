# Dependency-free behavioral tests; synthetic data only.
script <- normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[1]), mustWork = TRUE)
source(file.path(dirname(dirname(script)), "load.R"), encoding = "UTF-8")
results <- list()
test <- function(name, code) {
  issue <- tryCatch({ force(code); NULL }, error = function(e) conditionMessage(e))
  results[[length(results) + 1L]] <<- list(test = name, status = if (is.null(issue)) "PASS" else "FAIL", reason = issue)
  cat(if (is.null(issue)) "PASS" else "FAIL", name, if (!is.null(issue)) issue else "", "\n")
}
equal <- function(actual, expected, tolerance = 1e-7) {
  if (length(actual) != length(expected) || any(!is.finite(actual)) || any(abs(actual - expected) > tolerance))
    stop("Expected ", paste(expected, collapse = ", "), "; got ", paste(actual, collapse = ", "))
}
rejects <- function(code, pattern) {
  e <- tryCatch({ force(code); NULL }, error = function(e) conditionMessage(e))
  if (is.null(e) || !grepl(pattern, e, ignore.case = TRUE)) stop("Expected rejection matching: ", pattern, "; got: ", e)
}
meta <- list(drug = "TestDrug", species = "synthetic", matrix = "plasma", concentration_unit = "mg/L",
             time_unit = "h", dose_unit = "mg", route = "IV", concentration_basis = "total",
             record_level = "individual", data_origin = "synthetic", regimen_type = "single_dose")
idx <- function(t, c, mic = 1, window = range(t), ...) pkpd_indices(t, c, mic, window, meta, output_basis = "total", ...)
dose <- data.frame(time_h = 0, dose_mg = 100, duration_h = 0)

test("constant profile and threshold equality", {
  z <- idx(c(0, 4), c(2, 2), 2)
  equal(z$AUC_mg_h_L, 8); equal(z$time_above_MIC_h, 0); equal(z$Cmax_MIC, 1)
  equal(idx(c(0, 4), c(2, 2), 1)$percent_time_above_MIC, 100)
})
test("linear triangle with ascending and descending crossings", {
  z <- idx(c(0, 2, 4), c(0, 4, 0), 2)
  equal(z$AUC_mg_h_L, 8); equal(z$time_above_MIC_h, 2); equal(z$percent_time_above_MIC, 50)
})
test("exact log-down integration and crossing", {
  z <- idx(c(0, 6), 8 * exp(-0.5 * c(0, 6)), 2, method = "linear_up_log_down")
  equal(z$AUC_mg_h_L, 16 * (1 - exp(-3)))
  equal(z$time_above_MIC_h, log(4) / 0.5)
})
test("clipped window retains exponential interpolation", {
  z <- idx(c(0, 6), 8 * exp(-0.5 * c(0, 6)), window = c(1, 4), method = "linear_up_log_down")
  equal(z$AUC_mg_h_L, 16 * (exp(-0.5) - exp(-2)))
  equal(z$Cmax_profile_mg_L, 8 * exp(-0.5))
})
test("zero concentrations use valid linear interpolation", {
  z <- idx(c(0, 1, 2), c(0, 2, 0), method = "linear_up_log_down")
  equal(z$AUC_mg_h_L, 2); equal(z$time_above_MIC_h, 1)
})
test("unordered observations are sorted as paired values", {
  equal(idx(c(4, 0, 2), c(0, 0, 4), 2)$AUC_mg_h_L, 8)
})
test("free conversion changes AUC and threshold consistently", {
  z <- pkpd_indices(c(0, 2), c(4, 4), 1, c(0, 2), meta, fu = 0.25)
  equal(z$AUC_mg_h_L, 2); equal(z$percent_time_above_MIC, 0)
  rejects(pkpd_indices(c(0, 2), c(4, 4), 1, c(0, 2), meta), "fu")
  rejects(pkpd_indices(c(0, 2), c(4, 4), 1, c(0, 2), meta, fu = 1.2), "fu")
  rejects(idx(c(0, 2), c(4, 4), fu = 0.5), "basis")
})
test("free profile is not silently corrected twice or back-calculated", {
  m <- meta; m$concentration_basis <- "free"
  equal(pkpd_indices(c(0, 2), c(4, 4), 1, c(0, 2), m)$AUC_mg_h_L, 8)
  rejects(pkpd_indices(c(0, 2), c(4, 4), 1, c(0, 2), m, fu = 0.5), "basis")
  rejects(pkpd_indices(c(0, 2), c(4, 4), 1, c(0, 2), m, output_basis = "total"), "back-calculation")
})
test("data gaps and invalid values are rejected", {
  rejects(idx(c(0, 2), c(4, 2), window = c(0, 3)), "not covered")
  rejects(idx(c(0, 0, 2), c(4, 3, 2)), "Duplicate")
  rejects(idx(c(0, 2), c(4, NA)), "finite")
  rejects(idx(c(0, 2), c(-1, 2)), "nonnegative")
  rejects(idx(c(0, 2), c(4, 2), mic = 0), "positive")
  rejects(idx(c(0, 2), c(4, 2), discontinuities_h = 1), "discontinuity")
})
test("unit and metadata ambiguity block numerical analysis", {
  m <- meta; m$concentration_unit <- "ug/mL"
  rejects(pkpd_indices(c(0, 2), c(4, 2), 1, c(0, 2), m), "mg/L")
  m <- meta; m$species <- "NOT_FOUND"
  rejects(pkpd_indices(c(0, 2), c(4, 2), 1, c(0, 2), m), "explicitly supplied")
})
test("one-compartment bolus limits and mass balance", {
  equal(pk_1cpt(c(-1, 0, 3), 2, 10, dose), c(0, 10, 10 * exp(-0.6)))
  auc <- integrate(function(t) pk_1cpt(t, 2, 10, dose), 0, Inf)$value
  equal(auc, 100 / 2, 1e-5)
})
test("two-compartment central initial value and mass balance", {
  equal(pk_2cpt(c(-1, 0), 2, 8, 3, 16, dose), c(0, 12.5))
  equal(integrate(function(t) pk_2cpt(t, 2, 8, 3, 16, dose), 0, Inf)$value, 50, 1e-5)
})
test("infusion is continuous and conserves dose/clearance AUC", {
  d <- dose; d$duration_h <- 2
  equal(pk_1cpt(c(0, 2), 2, 10, d), c(0, 25 * (1 - exp(-0.4))))
  equal(pk_1cpt(2 - 1e-8, 2, 10, d), pk_1cpt(2 + 1e-8, 2, 10, d), 1e-6)
  equal(integrate(function(t) pk_1cpt(t, 2, 10, d), 0, 2)$value +
          integrate(function(t) pk_1cpt(t, 2, 10, d), 2, Inf)$value, 50, 1e-5)
  equal(integrate(function(t) pk_2cpt(t, 2, 8, 3, 16, d), 0, 2)$value +
          integrate(function(t) pk_2cpt(t, 2, 8, 3, 16, d), 2, Inf)$value, 50, 1e-5)
})
test("repeated bolus superposition", {
  d <- rbind(dose, transform(dose, time_h = 6, dose_mg = 60))
  t <- c(0, 5, 6, 8, 20)
  equal(pk_1cpt(t, 2, 10, d), pk_1cpt(t, 2, 10, dose) + pk_1cpt(t, 2, 10, d[2, ]))
})
set.seed(916)
t <- c(0.1, 0.25, 0.5, 1, 2, 3, 4, 6, 8, 12, 18, 24)
one <- data.frame(subject_id = "S", time_h = t,
                   concentration_mg_L = pk_1cpt(t, 2, 12, dose) * exp(rnorm(length(t), 0, 0.006)))
fit_one <- NULL
test("individual lognormal fit recovers parameters", {
  fit_one <<- fit_pk_individual(one, dose, meta)
  stopifnot(all(abs(fit_one$theta / c(CL = 2, V = 12) - 1) < 0.025))
  stopifnot(all(fit_one$parameters$CI_lower > 0), all(fit_one$parameters$RSE_percent >= 0))
})
test("individual additive-error fit recovers parameters", {
  z <- fit_pk_individual(one, dose, meta, error = "additive")
  stopifnot(all(abs(z$theta / c(CL = 2, V = 12) - 1) < 0.04))
})
test("two-compartment fit recovers four parameters", {
  d <- one; d$concentration_mg_L <- pk_2cpt(t, 2, 8, 3, 16, dose) * exp(0.002 * sin(seq_along(t)))
  z <- fit_pk_individual(d, dose, meta, compartments = 2, start = c(CL = 1.8, Vc = 9, Q = 2.5, Vp = 15))
  stopifnot(all(abs(z$theta / c(CL = 2, Vc = 8, Q = 3, Vp = 16) - 1) < 0.06))
})
test("PK rejects BLQ, duplicate occasions and implicit species pooling", {
  d <- one; d$blq <- TRUE
  rejects(fit_pk_individual(d, dose, meta), "BLQ")
  rejects(fit_pk_individual(rbind(one, one[1, ]), dose, meta), "Duplicate")
  d <- one; d$species <- "different_species"
  rejects(fit_pk_individual(d, dose, meta), "species")
  d <- one; d$concentration_mg_L[1] <- 0
  rejects(fit_pk_individual(d, dose, meta), "positive")
})
test("event-split AUC matches analytic repeated-bolus integral", {
  z <- fit_one; z$theta <- c(CL = 2, V = 10)
  z$doses <- data.frame(time_h = c(0, 6, 12), dose_mg = c(100, 60, 1000), duration_h = 0)
  out <- indices_from_pk_fit(z, 1, c(0, 12), output_basis = "total", step_h = 1.3)
  expected <- 100 / 2 * (1 - exp(-0.2 * 12)) + 60 / 2 * (1 - exp(-0.2 * 6))
  equal(out$AUC_mg_h_L, expected, 1e-8)
  equal(out$Cmax_profile_mg_L, 10)
  equal(out$n_continuous_segments, 2)
  # The large bolus exactly at t=12 must affect neither AUC nor this window's Cmax.
  z$doses <- z$doses[1:2, ]
  equal(indices_from_pk_fit(z, 1, c(0, 12), output_basis = "total")$AUC_mg_h_L, expected, 1e-8)
})
test("event-split infusion converges to quadrature result", {
  z <- fit_one; z$doses <- transform(dose, time_h = 2, duration_h = 1.5)
  a <- indices_from_pk_fit(z, 1, c(0, 12), output_basis = "total", step_h = 0.01)
  expected <- integrate(function(t) predict_pk(z, t), 2, 3.5)$value +
    integrate(function(t) predict_pk(z, t), 3.5, 12)$value
  equal(a$AUC_mg_h_L, expected, 0.001)
})
set.seed(211)
pop <- do.call(rbind, lapply(seq_len(24), function(i) {
  cl <- 2 * exp(rnorm(1, 0, 0.15)); v <- 12 * exp(rnorm(1, 0, 0.12))
  data.frame(subject_id = paste0("P", i), time_h = t, dose_mg = 100, dose_time_h = 0, duration_h = 0,
               concentration_mg_L = pk_1cpt(t, cl, v, dose) * exp(rnorm(length(t), 0, 0.04)))
}))
fit_pop <- NULL
test("population repeated-measure PK recovers typical parameters", {
  fit_pop <<- fit_population_pk(pop, meta)
  stopifnot(all(abs(fit_pop$parameters$estimate / c(2, 12) - 1) < 0.1))
  equal(fit_pop$diagnostics$n_subjects, 24)
  equal(predict_population_pk(fit_pop, fit_pop$data, individual = TRUE), fit_pop$predicted)
  stopifnot(all(is.finite(predict_population_pk(fit_pop, data.frame(time_h = c(1, 3), dose_mg = 100)))))
})
test("population PK enforces its single-bolus and individual-record contract", {
  m <- meta; m$record_level <- "summary"
  rejects(fit_population_pk(pop, m), "individual records")
  m <- meta; m$regimen_type <- "multiple_dose"
  rejects(fit_population_pk(pop, m), "single_dose")
  d <- pop; d$duration_h <- 1
  rejects(fit_population_pk(d, meta), "single IV bolus")
  d <- pop; d$dose_mg[1] <- 200
  rejects(fit_population_pk(d, meta), "constant within subject")
  rejects(predict_population_pk(fit_pop, data.frame(time_h = 1, dose_mg = 100, subject_id = "new"), TRUE), "fitted subject")
})
set.seed(135)
x <- c(0, exp(seq(log(0.5), log(250), length.out = 59)))
endpoint <- data.frame(unit_id = paste0("E", seq_along(x)), study_id = rep(c("A", "B", "C"), length.out = length(x)),
                        index = x, index2 = sqrt(x),
                        response = emax_response(x, 8, 5, 20) + rnorm(length(x), 0, 0.012))
fit_e <- NULL
test("Emax endpoint fit recovers baseline, effect and EC50", {
  fit_e <<- fit_index_emax(endpoint, "index")
  stopifnot(all(abs(fit_e$theta[c("E0", "Emax", "EC50")] / c(8, 5, 20) - 1) < 0.035))
  equal(predict_emax(fit_e, 0), fit_e$theta["E0"])
})
test("free Hill coefficient and increasing response are supported", {
  d <- endpoint; d$response <- emax_response(x, 2, 6, 15, 1.5, "increasing") + 0.008 * sin(seq_along(x))
  z <- fit_index_emax(d, "index", direction = "increasing", estimate_hill = TRUE)
  stopifnot(all(abs(z$theta / c(E0 = 2, Emax = 6, EC50 = 15, hill = 1.5) - 1) < 0.03))
})
test("endpoint regression rejects pseudoreplication and unsupported exposure", {
  d <- endpoint; d$unit_id[2] <- d$unit_id[1]
  rejects(fit_index_emax(d, "index"), "independent endpoint")
  d <- endpoint; d$index <- 1
  rejects(fit_index_emax(d, "index"), "exposure support")
  d <- endpoint; d$response <- 1
  rejects(fit_index_emax(d, "index"), "Constant response")
})
test("candidate indices share observations and withhold whole groups", {
  z <- compare_pkpd_indices(endpoint, c("index", "index2"), group_col = "study_id")
  stopifnot(all(z$comparison$folds_successful == 3), all(is.finite(z$comparison$grouped_CV_RMSE)))
  stopifnot(all(vapply(z$fold_results, function(f) f$n_test == 20, logical(1))))
  d <- endpoint; d$index2[1] <- NA_real_
  rejects(compare_pkpd_indices(d, c("index", "index2")), "same complete")
})
test("failed held-out folds do not produce a partial CV score", {
  d <- endpoint[1:12, ]; d$study_id <- c(rep("A", 10), "B", "C")
  z <- compare_pkpd_indices(d, c("index", "index2"), group_col = "study_id")
  stopifnot(all(z$comparison$folds_successful < z$comparison$folds_total), all(is.na(z$comparison$grouped_CV_RMSE)))
})
set.seed(16)
long <- do.call(rbind, lapply(seq_len(20), function(i) {
  t <- seq(0, 12, by = 1.5); exposure <- runif(1, 0.5, 4) * exp(-0.06 * t); b <- rnorm(1, 0, 0.4)
  data.frame(subject_id = paste0("L", i), time_h = t, exposure = exposure,
               response = 10 + 0.25 * t - 0.01 * t^2 - 1.2 * exposure + b + rnorm(length(t), 0, 0.1))
}))
fit_l <- NULL
test("generic longitudinal regression estimates an exposure association", {
  fit_l <<- fit_response_longitudinal(long, "arbitrary units")
  effect <- fit_l$parameters$estimate[fit_l$parameters$parameter == "exposure"]
  equal(effect, -1.2, 0.2)
  equal(predict_response_longitudinal(fit_l, fit_l$data, TRUE), fit_l$predicted)
  stopifnot(all(is.finite(predict_response_longitudinal(fit_l, long[1:2, ]))))
})
test("longitudinal response rejects implicit extrapolation and ambiguous units", {
  rejects(predict_response_longitudinal(fit_l, data.frame(time_h = 20, exposure = 1)), "extrapolation")
  rejects(fit_response_longitudinal(long, "NOT_FOUND"), "response_unit")
  d <- long; d$exposure <- 1
  rejects(fit_response_longitudinal(d, "arbitrary units"), "constant exposure")
  rejects(fit_response_longitudinal(rbind(long, long[1, ]), "arbitrary units"), "duplicate")
})
test("continuous-time residual correlation option fits irregular times", {
  # Correlated synthetic noise at unequal time spacing.
  d <- long; d$time_h <- d$time_h + 0.04 * (d$time_h / 1.5)^2
  z <- fit_response_longitudinal(d, "arbitrary units", serial_correlation = TRUE)
  stopifnot(isTRUE(z$diagnostics$serial_correlation), all(is.finite(z$predicted)))
})
test("JSON retains parameter names, matrix labels and numeric null", {
  file <- tempfile(fileext = ".json")
  m <- matrix(1:4, 2, dimnames = list(c("a", "b"), c("a", "b")))
  write_pkpd_json(list(theta = c(CL = 2, V = 12), covariance = m, missing = NA_real_), file)
  z <- jsonlite::read_json(file)
  equal(z$theta$CL, 2); equal(z$theta$V, 12)
  stopifnot(identical(unlist(z$covariance$row_names), c("a", "b")), is.null(z$missing))
})
test("fit export round-trips RDS predictions and provenance", {
  folder <- tempfile("pkpd-export-")
  export_pkpd_fit(fit_e, folder, list(data_origin = "synthetic", source = "run_tests.R"))
  z <- readRDS(file.path(folder, "model.rds"))
  equal(predict_emax(z, c(0, 5, 20)), predict_emax(fit_e, c(0, 5, 20)))
  manifest <- jsonlite::read_json(file.path(folder, "result.json"))
  stopifnot(manifest$provenance$data_origin == "synthetic", file.exists(file.path(folder, "parameters.csv")))
})
test("local parameter precision is not labeled external validation", {
  stopifnot(grepl("not external", fit_one$diagnostics$inference_limit))
  stopifnot(grepl("not a mechanistic", fit_l$diagnostics$scope))
})
test("mass-normalized fit agrees with an absolute-dose representation", {
  dm <- data.frame(time_h = 0, dose_mg_kg = 1, duration_h = 1/60)
  m <- meta; m$dose_unit <- "mg/kg"
  absolute <- data.frame(time_h = 0, dose_mg = 0.31, duration_h = 1/60)
  d <- one; d$concentration_mg_L <- pk_1cpt(d$time_h, 0.2*0.31, 0.4*0.31, absolute) * exp(0.006*sin(seq_len(nrow(d))))
  z <- fit_pk_per_kg(d, dm, m)
  a <- fit_pk_individual(d, absolute, meta)
  equal(z$theta, a$theta / 0.31, 1e-7)
  equal(predict_pk(z, c(0, 0.01, 0.1, 6)), predict_pk(a, c(0, 0.01, 0.1, 6)), 1e-7)
  stopifnot(identical(z$parameters$unit, c("L/h/kg", "L/kg")), z$meta$dose_unit == "mg/kg")
})
test("normalized finite-infusion population model recovers parameters", {
  set.seed(891)
  popn <- do.call(rbind, lapply(seq_len(24), function(i) {
    tt <- c(0.17, 0.33, 0.5, 1, 2, 3, 4, 6)
    cl <- 0.2*exp(rnorm(1,0,0.1)); v <- 0.4*exp(rnorm(1,0,0.1))
    data.frame(subject_id=paste0("N",i), time_h=tt, dose_mg_kg=1, dose_time_h=0, duration_h=1/60,
      concentration_mg_L=pk_1cpt(tt,cl,v,data.frame(time_h=0,dose_mg=1,duration_h=1/60))*exp(rnorm(length(tt),0,0.025)))
  }))
  m <- meta; m$dose_unit <- "mg/kg"
  normalized_population_fit <<- fit_population_pk_infusion_per_kg(popn,m,c(CL=0.2,V=0.4))
  z <- normalized_population_fit
  stopifnot(all(abs(z$parameters$estimate / c(0.2,0.4)-1) < 0.1))
  equal(predict_population_pk_infusion_per_kg(z,z$data,TRUE),z$predicted,1e-8)
})
test("finite-infusion population prediction includes pre/during/post dose", {
  z <- normalized_population_fit
  nd <- data.frame(time_h=c(-1,0,0.008,1/60,0.17,6),dose_time_h=0,dose_mg_kg=1,duration_h=1/60)
  p <- z$parameters$estimate
  equal(predict_population_pk_infusion_per_kg(z,nd),
    pk_1cpt(nd$time_h,p[1],p[2],data.frame(time_h=0,dose_mg=1,duration_h=1/60)),1e-10)
  nd$subject_id <- "unseen"
  rejects(predict_population_pk_infusion_per_kg(z,nd,TRUE),"Unknown individual")
})
test("normalized infusion fitting enforces units and observation support", {
  z <- normalized_population_fit
  m <- z$meta; m$dose_unit <- "mg"
  rejects(fit_population_pk_infusion_per_kg(z$data,m,c(CL=0.2,V=0.4)),"mg/kg")
  d <- z$data; d$time_h[1] <- 0.001
  rejects(fit_population_pk_infusion_per_kg(d,z$meta,c(CL=0.2,V=0.4)),"post-infusion")
})
failures <- sum(vapply(results, function(r) r$status == "FAIL", logical(1)))
report <- list(software_version = PKPD_VERSION, passed = length(results) - failures, failed = failures,
                 data_origin = "synthetic", tests = results)
args <- commandArgs(trailingOnly = TRUE)
if (length(args)) write_pkpd_json(report, args[1])
cat(sprintf("\n%d passed; %d failed.\n", report$passed, failures))
if (failures) quit(status = 1)
