# Declared descriptive endpoint analysis, separate from PK/PD-index selection.
args <- commandArgs(trailingOnly=TRUE)
if(length(args)!=2) stop("Expected input.json and a new results directory")
script <- normalizePath(sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1]),mustWork=TRUE)
source(file.path(dirname(dirname(script)),"load.R"),encoding="UTF-8")
source(file.path(dirname(dirname(script)),"modules/shared.R"),encoding="UTF-8")
request <- jsonlite::read_json(args[1],simplifyVector=FALSE)
data <- records_frame(request$records)
out <- args[2]
if(dir.exists(out)) stop("Preserve existing runs; use a new results directory")
dir.create(out,recursive=TRUE)
stopifnot(all(data$time_h==1),all(data$CENS==0),all(data$status=="QUANTIFIED"),
          all(data$independent_replicate_id=="NOT_FOUND"),!anyDuplicated(data$experiment_group_key))
rows <- list(); fits <- list(); predictions <- list(); parameters <- list()
for(strain in unique(data$strain)) {
  d <- data[data$strain==strain,,drop=FALSE]
  stopifnot(nrow(d)==6,length(unique(d$nominal_concentration_mg_L))==6)
  for(hill in c(FALSE,TRUE)) {
    name <- if(hill) "Hill" else "Emax"
    key <- paste(strain,name,sep="_")
    # Explicit sparse-review switch: production module defaults remain unchanged.
    # Unexpected fitting errors propagate and stop this run, as requested.
    fit <- fit_index_emax(d,"nominal_concentration_mg_L","log10_CFU_mL",
      "experiment_group_key",estimate_hill=hill,sparse_exploratory=hill)
    fit$response_unit <- "log10 CFU/mL at 1 hour"
    fit$diagnostics$n_independent_units <- NULL
    fit$diagnostics$n_endpoint_groups <- nrow(d)
    fit$diagnostics$independent_biological_replicates <- "NOT_FOUND"
    fit$diagnostics$model <- "Conditional independent equal-variance Gaussian endpoint errors; biological independence unverified; nominal concentration error ignored"
    fit$warnings <- unique(c(fit$warnings,"Nominal static concentration, not a free-drug PK/PD index. Independent biological replicate identifiers are missing."))
    p <- fit$parameters
    finite_ci <- all(is.finite(as.matrix(p[c("estimate","SE","CI_lower","CI_upper")])))
    positive_covariance <- all(eigen(fit$covariance_parameters,symmetric=TRUE,only.values=TRUE)$values>0)
    corr <- cov2cor(fit$covariance_parameters)
    maxcorr <- max(abs(corr[upper.tri(corr)]))
    issues <- character()
    if(!finite_ci || !positive_covariance) issues <- c(issues,"Unusable parameter covariance or interval")
    if(any(grepl("bound",fit$warnings,fixed=TRUE))) issues <- c(issues,"Numerical parameter-bound sensitivity")
    status <- if(length(issues)) "REJECTED_IDENTIFIABILITY_SCREEN" else "EXPLORATORY_CANDIDATE_PENDING_REVIEW"
    rows[[key]] <- data.frame(strain=strain,model=name,n=nrow(d),n_parameters=fit$diagnostics$n_parameters,
      residual_df=stats::df.residual(fit$fit),R2=1-sum((d$log10_CFU_mL-fit$predicted)^2)/sum((d$log10_CFU_mL-mean(d$log10_CFU_mL))^2),
      AIC=fit$diagnostics$AIC,AICc=fit$diagnostics$AICc,BIC=fit$diagnostics$BIC,
      RMSE=fit$diagnostics$RMSE_original_scale,max_abs_parameter_correlation=maxcorr,
      max_RSE_percent=max(p$RSE_percent,na.rm=TRUE),status=status,reason=paste(issues,collapse="; "))
    parameters[[key]] <- data.frame(strain=strain,model=name,p)
    predictions[[key]] <- data.frame(strain=strain,model=name,record_id=d$record_id,
      concentration_mg_L=d$nominal_concentration_mg_L,observed=d$log10_CFU_mL,predicted=fit$predicted)
    export_pkpd_fit(fit,file.path(out,"models",key),request$provenance)
    fits[[key]] <- fit
  }
}
comparison <- do.call(rbind,rows);rownames(comparison)<-NULL
recommendations <- lapply(split(comparison,comparison$strain),function(x) {
  eligible <- x$status=="EXPLORATORY_CANDIDATE_PENDING_REVIEW"
  list(strain=x$strain[1],lowest_AIC=x$model[which.min(x$AIC)],highest_R2=x$model[which.max(x$R2)],
    best_after_screen_by_AIC=if(any(eligible)) x$model[which(eligible)[which.min(x$AIC[eligible])]] else NULL,
    AICc_comparison="NOT_AVAILABLE_FOR_HILL_AT_N6",predictive_winner="NOT_ESTABLISHED",
    human_review="PENDING")
})
utils::write.csv(comparison,file.path(out,"comparison.csv"),row.names=FALSE,na="")
utils::write.csv(do.call(rbind,parameters),file.path(out,"parameters.csv"),row.names=FALSE,na="")
utils::write.csv(do.call(rbind,predictions),file.path(out,"predictions.csv"),row.names=FALSE,na="")
png(file.path(out,"emax_hill_fits.png"),width=1500,height=730,res=140)
par(mfrow=c(1,2),mar=c(5,4.5,3,1))
for(strain in unique(data$strain)) {
  d <- data[data$strain==strain,,drop=FALSE]
  # Display the 1e-8 control near zero on a linear axis; fit uses its exact value.
  plot(d$nominal_concentration_mg_L,d$log10_CFU_mL,pch=16,xlab="Nominal PMB concentration (mg/L)",
       ylab="log10 CFU/mL at 1 h",main=paste(strain,"(6 concentration groups)"),ylim=range(data$log10_CFU_mL))
  grid <- seq(min(d$nominal_concentration_mg_L),max(d$nominal_concentration_mg_L),length.out=500)
  for(i in 1:2) lines(grid,predict_emax(fits[[paste(strain,c("Emax","Hill")[i],sep="_")]],grid),
                      col=c("#2371A0","#B85B27")[i],lty=i,lwd=2)
  legend("topright",c("Observed group endpoint","Emax (Hill = 1)","Hill (sparse exploratory)"),
         pch=c(16,NA,NA),lty=c(NA,1,2),col=c("black","#2371A0","#B85B27"),bty="n",cex=.8)
}
dev.off()
write_pkpd_json(list(status="COMPLETED_PENDING_HUMAN_REVIEW",
  analysis_type="static_concentration_endpoint_emax_hill",provenance=request$provenance,
  equation="E0 - Emax*C^h/(EC50^h+C^h); Emax h=1, Hill h estimated; endpoint=log10 CFU/mL at 1 h",
  comparison=comparison,recommendations=unname(recommendations),
  qualifications=list("One-hour endpoint chosen for common uncensored support, not on fitted R2",
    "Six concentration groups per strain; biological replicate identity NOT_FOUND",
    "Hill uses declared sparse exploratory mode (2 residual degrees of freedom); standard index module retains its default data guard",
    "AICc uses k including residual variance; Hill n=6 k=5 implies undefined AICc",
    "No held-out validation: apparent fit is not predictive reliability",
    "Nominal static C; independent ranking of fAUC/MIC, fCmax/MIC and fT>MIC is not established",
    "Refit of supplied endpoints, not a reproduction of the original longitudinal PSP model"),
  human_review=list(status="PENDING",decision="PENDING",reviewer="",approved_for_downstream_use=FALSE)),file.path(out,"output.json"))
cat("Static Emax/Hill review complete:",out,"\n")
