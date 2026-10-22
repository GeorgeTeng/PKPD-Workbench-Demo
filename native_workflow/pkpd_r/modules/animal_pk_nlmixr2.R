# Trusted IV compartment model worker. Only enumerated templates and numeric
# configuration values enter the generated model; no caller-supplied R is run.
args <- commandArgs(trailingOnly = TRUE)
lib <- Sys.getenv("PKPD_R_LIB", unset = "C:/Users/georg/Documents/Codex/ScienceEnv/R-library")
if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
needed <- c("jsonlite", "nlmixr2", "nlmixr2est", "rxode2")
ready <- vapply(needed, requireNamespace, logical(1), quietly = TRUE)
if (length(args) == 1L && identical(args[1], "--preflight")) {
  if (!ready[["jsonlite"]]) { cat("Required R package jsonlite is missing.\n"); quit(status = 2L) }
  versions <- setNames(lapply(needed, function(p) if (ready[[p]]) as.character(packageVersion(p)) else NULL), needed)
  cat("PK_ENGINE_JSON=", jsonlite::toJSON(list(packages_ready = all(ready), packages = versions,
      r_version = R.version.string), auto_unbox = TRUE, null = "null"), "\n", sep = "")
  quit(status = if (all(ready)) 0L else 2L)
}
if (length(args) != 2L) stop("Usage: animal_pk_nlmixr2.R input.json raw_result.json")
if (!all(ready)) stop("Missing R package(s): ", paste(needed[!ready], collapse = ", "))
suppressPackageStartupMessages(library(nlmixr2))
out <- args[2]
directory <- dirname(out)
write_result <- function(value) jsonlite::write_json(value, out, auto_unbox = TRUE, pretty = TRUE,
                                                    null = "null", na = "null", digits = NA)
number <- function(x) {
  if (!is.numeric(x) || length(x) != 1L || !is.finite(x)) stop("Model template accepts only finite numeric values.")
  format(x, digits = 17L, scientific = TRUE, trim = TRUE)
}
scalar <- function(x) if (length(x) == 1L && is.numeric(x) && is.finite(x)) as.numeric(x) else NULL
warnings_seen <- character()
status <- tryCatch(withCallingHandlers({
  request <- jsonlite::read_json(args[1], simplifyVector = FALSE)
  if (!identical(request$schema_version, "1.0")) stop("Unsupported worker input schema.")
  cfg <- request$config
  if (!identical(cfg$engine, "nlmixr2") || !identical(cfg$estimator, "focei")) stop("Unsupported fitting engine or estimator.")
  ncomp <- request$compartments
  if (!ncomp %in% 1:3) stop("Unsupported compartment structure.")
  structural <- switch(as.character(ncomp), `1` = c("CL", "VC"), `2` = c("CL", "VC", "Q", "VP"),
                       `3` = c("CL", "VC", "Q", "VP", "Q2", "VP2"))
  effects <- unlist(cfg$random_effects, use.names = FALSE)
  if (!all(effects %in% structural) || anyDuplicated(effects)) stop("Invalid random-effect configuration.")
  if (!setequal(names(cfg$initial), structural) || !setequal(names(cfg$bounds), structural)) stop("Missing or extra structural parameters.")
  ini_lines <- vapply(structural, function(p) {
    bounds <- unlist(cfg$bounds[[p]], use.names = FALSE)
    value <- cfg$initial[[p]]
    if (length(bounds) != 2L || !all(is.finite(c(bounds, value))) || !(0 < bounds[1] && bounds[1] < value && value < bounds[2])) stop("Invalid parameter bounds.")
    paste0("t", tolower(p), " <- c(", number(log(bounds[1])), ", ", number(log(value)), ", ", number(log(bounds[2])), ")")
  }, character(1))
  if (length(effects)) ini_lines <- c(ini_lines, vapply(effects, function(p) {
    if (cfg$omega_initial[[p]] <= 0) stop("Invalid initial variance.")
    paste0("eta.", tolower(p), " ~ ", number(cfg$omega_initial[[p]]))
  }, character(1)))
  error <- cfg$error_model
  if (!error %in% c("additive", "proportional", "combined")) stop("Unsupported residual error model.")
  if (error %in% c("additive", "combined")) ini_lines <- c(ini_lines, paste0("add.sd <- ", number(cfg$residual_initial$additive)))
  if (error %in% c("proportional", "combined")) ini_lines <- c(ini_lines, paste0("prop.sd <- ", number(cfg$residual_initial$proportional)))
  model_lines <- vapply(structural, function(p) paste0(tolower(p), " <- exp(t", tolower(p),
                                    if (p %in% effects) paste0(" + eta.", tolower(p)) else "", ")"), character(1))
  # The documented analytical linear-compartment solver recognizes CL/VC,
  # Q/VP and Q2/VP2. It avoids needless ODE work and derivative noise for these
  # strictly linear IV models. CMT=1 is central; RATE is handled by rxode2.
  model_lines <- c(model_lines,
    switch(error, additive = "linCmt() ~ add(add.sd)", proportional = "linCmt() ~ prop(prop.sd)",
           combined = "linCmt() ~ add(add.sd) + prop(prop.sd)"))
  text <- c("function() {", "  ini({", paste0("    ", ini_lines), "  })", "  model({",
            paste0("    ", model_lines), "  })", "}")
  writeLines(text, file.path(directory, "model.R"))
  model_function <- eval(parse(text = text), envir = .GlobalEnv)
  records <- request$records
  data <- data.frame(ID = vapply(records, function(x) as.character(x$ID), character(1)),
                     TIME = vapply(records, function(x) as.numeric(x$TIME), numeric(1)),
                     DV = vapply(records, function(x) if (is.null(x$DV)) 0 else as.numeric(x$DV), numeric(1)),
                     AMT = vapply(records, function(x) as.numeric(x$AMT), numeric(1)),
                     EVID = vapply(records, function(x) as.numeric(x$EVID), numeric(1)),
                     RATE = vapply(records, function(x) as.numeric(x$RATE), numeric(1)),
                     CMT = vapply(records, function(x) as.numeric(x$CMT), numeric(1)))
  # IDs are preserved in an explicit mapping; input subject identities are never fabricated.
  id_map <- data.frame(original_ID = unique(data$ID), engine_ID = seq_along(unique(data$ID)))
  data$ID <- id_map$engine_ID[match(data$ID, id_map$original_ID)]
  data <- data[order(data$ID, data$TIME, -data$EVID), ]
  write.csv(id_map, file.path(directory, "subject_id_map.csv"), row.names = FALSE)
  write.csv(data, file.path(directory, "engine_data.csv"), row.names = FALSE)
  set.seed(as.integer(cfg$seed))
  rxode2::setRxThreads(as.integer(cfg$cores))
  optimizer <- if (is.null(cfg$optimizer)) "bobyqa" else cfg$optimizer
  if (!optimizer %in% c("bobyqa", "nlminb")) stop("Unsupported optimizer.")
  control <- nlmixr2est::foceiControl(print = 10L, maxOuterIterations = as.integer(cfg$max_outer_iterations),
                                    seed = as.integer(cfg$seed), outerOpt = optimizer,
                                    rxControl = rxode2::rxControl(cores = as.integer(cfg$cores)))
  fit <- nlmixr2est::nlmixr(model_function, data, est = "focei", control = control)
  saveRDS(fit, file.path(directory, "fit.rds"))
  capture.output(print(fit), file = file.path(directory, "fit_summary.txt"))
  predictions <- as.data.frame(fit)
  if(!length(effects)&&!('PRED' %in% names(predictions))&&'IPRED' %in% names(predictions))predictions$PRED<-predictions$IPRED
  write.csv(predictions, file.path(directory, "predictions.csv"), row.names = FALSE)
  fixed <- nlmixr2est::fixef(fit)
  covariance <- tryCatch(as.matrix(stats::vcov(fit)), error = function(e) NULL)
  covariance_valid <- !is.null(covariance) && length(covariance) > 0L && all(is.finite(covariance)) &&
    isTRUE(tryCatch(all(eigen(covariance, symmetric = TRUE, only.values = TRUE)$values > 0), error = function(e) FALSE))
  parameters <- lapply(structural, function(p) {
    key <- paste0("t", tolower(p)); theta <- fixed[[key]]
    se <- if (!is.null(covariance) && key %in% rownames(covariance) && covariance[key, key] >= 0) sqrt(covariance[key, key]) else NULL
    list(parameter = p, estimate = exp(theta), unit = paste0(if (p %in% c("CL", "Q", "Q2")) "L/h" else "L",
         if (identical(request$metadata$parameter_basis,"PER_KG")) "/kg" else ""),
         typical_value_definition = "exp(population log parameter), eta=0; not arithmetic population mean",
         log_scale_SE = scalar(se), delta_method_RSE_percent = if (!is.null(se)) scalar(100 * se) else NULL,
         confidence_interval_95 = if (!is.null(se)) as.list(exp(theta + c(-1, 1) * 1.96 * se)) else NULL)
  })
  ll <- tryCatch(stats::logLik(fit), error = function(e) NULL)
  message <- tryCatch(as.character(fit$message), error = function(e) character())
  code <- tryCatch(as.integer(fit$convergence), error = function(e) integer())
  information <- tryCatch(as.character(fit$runInfo), error = function(e) character())
  # An explicit engine signal is retained, never substituted for scientific adequacy.
  convergence <- if (length(code) == 1L && is.finite(code)) identical(code, 0L) else if (length(message) && any(grepl("Normal exit|convergence", message, ignore.case = TRUE)) && !any(grepl("fail|limit|not converg", message, ignore.case = TRUE))) TRUE else NULL
  critical <- information[grepl("near boundary|not at minimum|not positive definite|non-positive definite|gradient problems|covariance not calculated|failed|not converg", information, ignore.case = TRUE)]
  prediction_columns <- intersect(c("PRED", "IPRED"), names(predictions))
  predictions_finite <- length(prediction_columns) > 0L && all(vapply(predictions[prediction_columns], function(x) all(is.finite(x) & x >= 0), logical(1)))
  # Additional diagnostics are descriptive and do not alter the numerical fit.
  structural_keys<-paste0('t',tolower(structural))
  structural_cov<-if(!is.null(covariance)&&all(structural_keys %in% rownames(covariance)))covariance[structural_keys,structural_keys,drop=FALSE] else NULL
  maxcorr<-if(!is.null(structural_cov)&&all(is.finite(structural_cov)))tryCatch(max(abs(cov2cor(structural_cov)[upper.tri(structural_cov)])),error=function(e)NA_real_) else NA_real_
  finite_ci<-all(vapply(parameters,function(p)!is.null(p$confidence_interval_95)&&all(is.finite(unlist(p$confidence_interval_95))),logical(1)))
  at_bound<-any(vapply(structural,function(p){v<-fixed[[paste0('t',tolower(p))]];b<-log(unlist(cfg$bounds[[p]]));min(abs(v-b))<1e-4},logical(1)))
  if(!is.null(covariance))write.csv(covariance,file.path(directory,'covariance.csv'))
  omega<-tryCatch(as.matrix(fit$omega),error=function(e)NULL)
  if(!is.null(omega))write.csv(omega,file.path(directory,'omega.csv'))
  shrink<-tryCatch(as.data.frame(fit$shrink),error=function(e)NULL)
  if(!is.null(shrink))write.csv(shrink,file.path(directory,'shrinkage.csv'))
  observation_rows<-if('EVID' %in% names(predictions))predictions[predictions$EVID==0,,drop=FALSE] else predictions
  r2<-function(y,p)1-sum((y-p)^2)/sum((y-mean(y))^2)
  metrics<-list()
  for(column in prediction_columns){
    y<-observation_rows$DV;p<-observation_rows[[column]]
    metrics[[column]]<-list(R2=r2(y,p),RMSE=sqrt(mean((y-p)^2)),MAE=mean(abs(y-p)),bias=mean(y-p))
  }
  theta<-setNames(vapply(parameters,function(p)p$estimate,numeric(1)),structural)
  typical_curve<-function(t,dose,duration){
    k10<-theta['CL']/theta['VC']
    conv<-function(rate){(-expm1(-rate*pmin(t,duration)))*exp(-rate*pmax(0,t-duration))/rate}
    if(ncomp==1)return(dose/duration/theta['VC']*conv(k10))
    if(ncomp==2){k12<-theta['Q']/theta['VC'];k21<-theta['Q']/theta['VP'];s<-k10+k12+k21
      alpha<-(s+sqrt(s*s-4*k10*k21))/2;beta<-k10*k21/alpha
      return(dose/duration/theta['VC']*((alpha-k21)/(alpha-beta)*conv(alpha)+(k21-beta)/(alpha-beta)*conv(beta)))}
    rep(NA_real_,length(t))
  }
  if(ncomp<=2&&identical(request$metadata$route,'IV_INFUSION')){
    ev<-data[data$EVID==1,,drop=FALSE];dose<-ev$AMT[1];duration<-dose/ev$RATE[1]
    grid<-seq(0,max(observation_rows$TIME),length.out=501)
    write.csv(data.frame(time_h=grid,typical_concentration_mg_L=typical_curve(grid,dose,duration)),file.path(directory,'typical_curve.csv'),row.names=FALSE)
    for(logy in c('','y')){
      png(file.path(directory,paste0('individual_fits_',if(logy=='y')'semilog' else 'linear','.png')),width=1600,height=1200,res=140)
      par(mfrow=c(3,4),mar=c(3.5,3.7,2,1))
      for(id in unique(observation_rows$ID)){
        z<-observation_rows[observation_rows$ID==id,,drop=FALSE];z<-z[order(z$TIME),]
        label<-as.character(id_map$original_ID[match(as.character(id),as.character(id_map$engine_ID))]);if(is.na(label))label<-as.character(id)
        plot(z$TIME,z$DV,log=logy,pch=16,xlab='Time (h)',ylab='PMB (mg/L)',main=label)
        if('PRED' %in% names(z))lines(z$TIME,z$PRED,col='#216e9c',lty=2)
        if('IPRED' %in% names(z))lines(z$TIME,z$IPRED,col='#b76129',lwd=2)
      }
      plot.new();legend('center',c('Observed','Population prediction','Conditional individual prediction'),pch=c(16,NA,NA),lty=c(NA,2,1),col=c('black','#216e9c','#b76129'),bty='n',cex=.8);dev.off()
    }
  }
  png(file.path(directory,'residual_diagnostics.png'),width=1400,height=1000,res=130)
  par(mfrow=c(2,2),mar=c(4,4,3,1))
  for(column in c('PRED','IPRED')){
    if(column %in% names(observation_rows)){plot(observation_rows[[column]],observation_rows$DV,pch=16,xlab=column,ylab='Observed PMB (mg/L)',main=paste('Observed vs',column));abline(0,1,col='grey')}else plot.new()
  }
  residual_name<-if('CWRES' %in% names(observation_rows))'CWRES' else if('IWRES' %in% names(observation_rows))'IWRES' else NULL
  if(!is.null(residual_name)){plot(observation_rows$TIME,observation_rows[[residual_name]],pch=16,xlab='Time (h)',ylab=residual_name,main='Residuals vs time');abline(h=0,col='grey');plot(observation_rows$PRED,observation_rows[[residual_name]],pch=16,xlab='PRED',ylab=residual_name,main='Residuals vs prediction');abline(h=0,col='grey')} else {plot.new();plot.new()}
  dev.off()
  derived<-list(Vss=sum(theta[intersect(c('VC','VP','VP2'),names(theta))]),unit=if(identical(request$metadata$parameter_basis,'PER_KG'))'L/kg' else 'L')
  write_result(list(status = "FITTED", engine = "nlmixr2", estimator = "focei", parameters = parameters,
                    fit_metrics=metrics,derived=derived,finite_structural_intervals=finite_ci,parameter_at_bound=at_bound,
                    max_structural_parameter_correlation=scalar(maxcorr),
                    log_likelihood = scalar(as.numeric(ll)), n_parameters = scalar(attr(ll, "df")),
                    AIC = scalar(tryCatch(stats::AIC(fit), error = function(e) NA_real_)),
                    BIC = scalar(tryCatch(stats::BIC(fit), error = function(e) NA_real_)),
                    optimizer_code = if (length(code) == 1L) scalar(code) else NULL,
                    optimizer_message = as.list(message), run_information = as.list(information),
                    engine_convergence_signal = convergence, covariance_available = !is.null(covariance),
                    covariance_positive_definite = covariance_valid, predictions_finite = predictions_finite,
                    critical_numerical_messages = as.list(critical),
                    warnings = as.list(unique(warnings_seen)),
                    likelihood_status = "APPROXIMATE_FOCEI_NOT_EXACT_ML"))
  0L
}, warning = function(w) {
  warnings_seen <<- c(warnings_seen, conditionMessage(w))
}), error = function(e) {
  write_result(list(status = "FAILED", reason = conditionMessage(e), warnings = as.list(unique(warnings_seen))))
  message(conditionMessage(e))
  1L
})
quit(status = status)
