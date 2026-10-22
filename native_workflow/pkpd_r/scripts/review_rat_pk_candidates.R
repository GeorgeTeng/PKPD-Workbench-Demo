# Exploratory rat PK structure review; retains rejected models and raw provenance.
args <- commandArgs(trailingOnly=TRUE)
if(length(args)!=2) stop("Expected input.json and new output directory")
script <- normalizePath(sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1]),mustWork=TRUE)
source(file.path(dirname(dirname(script)),"load.R"),encoding="UTF-8")
source(file.path(dirname(dirname(script)),"modules/shared.R"),encoding="UTF-8")
request <- jsonlite::read_json(args[1],simplifyVector=FALSE)
out <- args[2]
if(dir.exists(out)) stop("Preserve existing model runs; use a new output directory")
dir.create(out,recursive=TRUE)
data <- records_frame(request$records)
meta <- request$metadata
doses <- records_frame(request$doses)
validate_meta(meta,require_pk=FALSE)
stopifnot(identical(meta$concentration_basis,"total"),identical(meta$dose_unit,"mg/kg"),
          identical(meta$route,"IV"),all(data$status=="QUANTIFIED"),length(unique(data$subject_id))==11)
rows <- list(); parameters <- list(); starts_log <- list(); predictions <- list(); individual <- list()
for(id in sort(unique(data$subject_id))) {
  d <- data[data$subject_id==id,,drop=FALSE]
  line <- coef(lm(log(concentration_mg_L)~time_h,data=d))
  rate <- max(.01,-unname(line[2])); volume <- doses$dose_mg_kg[1]/exp(unname(line[1]))
  for(nc in 1:2) {
    key <- paste0(id,"_",nc,"cpt")
    starts <- if(nc==1) list(c(CL=rate*volume,V=volume),c(CL=.5*rate*volume,V=2*volume)) else
      lapply(c(.1,.5,2,10),function(ratio) c(CL=rate*volume,Vc=volume/2,Q=rate*volume*ratio,Vp=volume))
    fits <- list()
    for(i in seq_along(starts)) {
      attempt <- tryCatch(fit_pk_per_kg(d,doses,meta,nc,"lognormal",starts[[i]]),error=identity)
      starts_log[[length(starts_log)+1]] <- list(model=key,start=i,initial=starts[[i]],
        status=if(inherits(attempt,"error")) "REJECTED_NUMERICAL_START" else "CONVERGED",
        reason=if(inherits(attempt,"error")) conditionMessage(attempt) else NULL)
      if(!inherits(attempt,"error")) fits[[length(fits)+1]] <- attempt
    }
    if(!length(fits)) {
      rows[[key]] <- data.frame(subject_id=id,model=paste0(nc,"cpt"),n=nrow(d),AIC=NA_real_,AICc=NA_real_,BIC=NA_real_,
        RMSE_log=NA_real_,R2_log=NA_real_,max_abs_parameter_correlation=NA_real_,max_RSE_percent=NA_real_,
        starts_converged=0,status="REJECTED_FIT_FAILED",reason="All declared starts failed")
      next
    }
    fit <- fits[[which.min(vapply(fits,function(f) f$diagnostics$AIC,numeric(1)))]]
    covariance <- fit$covariance_log_parameters
    correlation <- suppressWarnings(cov2cor(covariance))
    maxcorr <- max(abs(correlation[upper.tri(correlation)]))
    finite_ci <- all(is.finite(as.matrix(fit$parameters[c("estimate","SE","CI_lower","CI_upper")])))
    positive_covariance <- all(eigen(covariance,symmetric=TRUE,only.values=TRUE)$values>0)
    reason <- character()
    if(!finite_ci || !positive_covariance) reason <- c(reason,"Parameter covariance/CI is not usable")
    if(nc==2 && maxcorr>.95) reason <- c(reason,"Catalog hard rejection: parameter correlation above 0.95")
    status <- if(length(reason)) "REJECTED_IDENTIFIABILITY" else "CANDIDATE_PENDING_HUMAN_REVIEW"
    rows[[key]] <- data.frame(subject_id=id,model=paste0(nc,"cpt"),n=nrow(d),AIC=fit$diagnostics$AIC,
      AICc=fit$diagnostics$AICc,BIC=fit$diagnostics$BIC,RMSE_log=fit$diagnostics$RMSE_on_fit_scale,
      R2_log=1-sum((log(d$concentration_mg_L)-log(fit$predicted))^2)/sum((log(d$concentration_mg_L)-mean(log(d$concentration_mg_L)))^2),
      max_abs_parameter_correlation=maxcorr,max_RSE_percent=max(fit$parameters$RSE_percent,na.rm=TRUE),
      starts_converged=length(fits),status=status,reason=paste(reason,collapse="; "))
    parameters[[key]] <- data.frame(subject_id=id,model=paste0(nc,"cpt"),fit$parameters)
    predictions[[key]] <- data.frame(subject_id=id,model=paste0(nc,"cpt"),time_h=d$time_h,observed=d$concentration_mg_L,predicted=fit$predicted)
    export_pkpd_fit(fit,file.path(out,"models",key),request$provenance)
    individual[[key]] <- fit
  }
}
ranking <- do.call(rbind,rows); rownames(ranking)<-NULL
recommendation <- lapply(split(ranking,ranking$subject_id),function(x) {
  valid <- x$status=="CANDIDATE_PENDING_HUMAN_REVIEW" & is.finite(x$AICc)
  list(subject_id=x$subject_id[1],best_numerical_AICc=if(any(is.finite(x$AICc))) x$model[which.min(x$AICc)] else NULL,
       recommended_after_screen=if(any(valid)) x$model[which(valid)[which.min(x$AICc[valid])]] else NULL,
       status="PENDING_HUMAN_REVIEW")
})
utils::write.csv(ranking,file.path(out,"model_comparison.csv"),row.names=FALSE,na="")
utils::write.csv(do.call(rbind,parameters),file.path(out,"parameters.csv"),row.names=FALSE,na="")
utils::write.csv(do.call(rbind,predictions),file.path(out,"predictions.csv"),row.names=FALSE,na="")
write_pkpd_json(starts_log,file.path(out,"optimization_starts.json"))
one_compartment <- individual[grepl("_1cpt$",names(individual))]
population_start <- c(CL=exp(mean(log(vapply(one_compartment,function(f) f$theta[["CL"]],numeric(1))))),
                      V=exp(mean(log(vapply(one_compartment,function(f) f$theta[["V"]],numeric(1))))))
population <- fit_population_pk_infusion_per_kg(data,meta,population_start)
export_pkpd_fit(population,file.path(out,"population_1cpt"),request$provenance)
png(file.path(out,"individual_fits.png"),width=1600,height=1200,res=140)
par(mfrow=c(3,4),mar=c(3.8,3.8,2,1))
for(id in sort(unique(data$subject_id))) {
  d <- data[data$subject_id==id,,drop=FALSE]
  plot(d$time_h,d$concentration_mg_L,log="y",pch=16,xlab="Time (h)",ylab="Total PMB (mg/L)",main=id)
  for(nc in 1:2) {
    f <- individual[[paste0(id,"_",nc,"cpt")]]
    if(!is.null(f)) {
      grid <- seq(min(d$time_h),max(d$time_h),length.out=100)
      lines(grid,predict_pk(f,grid),col=c("#2371A0","#B85B27")[nc],lty=nc,lwd=2)
    }
  }
}
plot.new(); legend("center",legend=c("Observed","1 compartment","2 compartments (may fail review)"),pch=c(16,NA,NA),lty=c(NA,1,2),col=c("black","#2371A0","#B85B27"),bty="n")
dev.off()
write_pkpd_json(list(status="COMPLETED_PENDING_HUMAN_REVIEW",scope="Rat-only exploratory structural model review",
  catalog_ids=list("PK_SYS_1C_LIN","PK_SYS_2C_LIN","INPUT_IV_INF"),provenance=request$provenance,
  observations=nrow(data),subjects=length(unique(data$subject_id)),comparison=ranking,
  recommendations=unname(recommendation),population_one_compartment=list(parameters=population$parameters,diagnostics=population$diagnostics),
  comparison_basis="Within each animal: identical observations, finite IV infusion and Gaussian log-concentration likelihood. Population and per-animal AIC values are not ranked together.",
  screened_rules=list(two_compartment_max_parameter_correlation=.95,requires_finite_ci=TRUE,requires_positive_parameter_covariance=TRUE),
  unresolved=list("No held-out validation executed", "BLQ exclusion may bias late-phase estimates", "Local Wald intervals do not establish biological precision", "No third-species fit or human prediction"),
  human_review=list(status="PENDING",decision="PENDING",reviewer="",approved_for_downstream_use=FALSE)),file.path(out,"output.json"))
cat("Rat PK review complete:",out,"\n")
