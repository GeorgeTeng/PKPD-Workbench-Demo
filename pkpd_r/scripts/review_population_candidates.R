main<-function() {
args<-commandArgs(trailingOnly=TRUE)
if(length(args)!=2)stop('Expected input.json and new output directory')
script<-normalizePath(sub('^--file=','',grep('^--file=',commandArgs(),value=TRUE)[1]),mustWork=TRUE)
base<-dirname(dirname(script));source(file.path(base,'load.R'),encoding='UTF-8')
source(file.path(base,'modules/shared.R'),encoding='UTF-8')
source(file.path(base,'R/population_candidates.R'),encoding='UTF-8')
request<-jsonlite::read_json(args[1],simplifyVector=FALSE);out<-args[2]
if(dir.exists(out))stop('Existing output preserved; choose a new path')
dir.create(out,recursive=TRUE);d<-records_frame(request$records);meta<-request$metadata
validate_meta(meta);stopifnot(meta$species=='rat',all(d$status=='QUANTIFIED'))
workers<-suppressWarnings(as.integer(Sys.getenv('PKPD_WORKERS','1')))
if(is.na(workers)||workers<1)stop('PKPD_WORKERS must be a positive integer')
workers<-min(workers,11L)
cluster<-NULL
if(workers>1L) {
  # PSOCK works on Windows. Each worker has one BLAS/OpenMP thread.
  Sys.setenv(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
  cluster<-parallel::makePSOCKcluster(workers,outfile=file.path(out,'parallel_workers.log'))
  on.exit(if(!is.null(cluster))parallel::stopCluster(cluster),add=TRUE)
  parallel::clusterExport(cluster,'base',envir=environment())
  parallel::clusterEvalQ(cluster,{
    source(file.path(base,'load.R'),encoding='UTF-8')
    source(file.path(base,'modules/shared.R'),encoding='UTF-8')
    source(file.path(base,'R/population_candidates.R'),encoding='UTF-8')
    NULL
  })
}
map_fits<-function(items,fun,...) {
  if(is.null(cluster)) lapply(items,fun,...) else parallel::parLapply(cluster,items,fun,...)
}
write_pkpd_json(list(workers=workers,backend=if(workers>1)'PSOCK' else 'serial',
  parallel_units=c('independent optimization starts','held-out animal folds'),
  blas_threads=1,random_sampling=FALSE),file.path(out,'compute_resources.json'))
specs<-data.frame(id=c('RAT_1C_DIAG_LOG','RAT_1C_COR_LOG','RAT_2C_DIAG_LOG','RAT_2C_COR_LOG','RAT_2C_ALL_LOG','RAT_1C_COMBINED','RAT_2C_COMBINED'),
  compartments=c(1,1,2,2,2,1,2),random=c('diag_clv','cor_clv','diag_clv','cor_clv','diag_all','diag_clv','diag_clv'),
  residual=c(rep('lognormal',5),'combined','combined'))
all_fits<-list();logs<-list();rows<-list()
for(j in seq_len(nrow(specs))) {
  s<-specs[j,];cat('START',s$id,'\n');flush.console()
  starts<-if(s$compartments==1)list(c(CL=.2,Vc=.375),c(CL=.14,Vc=.55)) else
    list(c(CL=.2,Vc=.15,Q=.08,Vp=.22),c(CL=.2,Vc=.25,Q=.2,Vp=.2),
         c(CL=.15,Vc=.08,Q=.3,Vp=.35),c(CL=.25,Vc=.3,Q=.03,Vp=.1))
  fits<-list()
  attempts<-map_fits(starts,function(start,d,meta,s) {
    tryCatch(fit_population_candidate(d,meta,s$compartments,start,s$random,s$residual),error=identity)
  },d=d,meta=meta,s=s)
  for(i in seq_along(starts)) {
    attempt<-attempts[[i]]
    logs[[paste(s$id,i,sep=':')]]<-list(candidate=s$id,start=i,initial=starts[[i]],
      status=if(inherits(attempt,'error'))'FAILED_NUMERICAL_START' else 'CONVERGED',
      reason=if(inherits(attempt,'error'))conditionMessage(attempt) else NULL)
    write_pkpd_json(logs,file.path(out,'optimization_starts.json'))
    if(!inherits(attempt,'error'))fits[[length(fits)+1]]<-attempt
  }
  if(!length(fits)) {
    rows[[s$id]]<-list(candidate=s$id,compartments=s$compartments,random_structure=s$random,residual=s$residual,
      status='REJECTED_ALL_STARTS_FAILED',AIC=NULL,BIC=NULL,starts_converged=0)
  } else {
    best<-fits[[which.min(vapply(fits,function(f)f$diagnostics$AIC,numeric(1)))]]
    export_pkpd_fit(best,file.path(out,'models',s$id),request$provenance)
    write_pkpd_json(list(omega=best$omega,random_effects=best$random_effects,random_structure=s$random,
      variance_parameters=coef(best$fit$modelStruct$varStruct,unconstrained=FALSE),
      sigma=best$fit$sigma,method=best$fit$method,rejection_reasons=best$rejection_reasons),file.path(out,'models',s$id,'random_effects.json'))
    rows[[s$id]]<-c(list(candidate=s$id,compartments=s$compartments,random_structure=s$random,residual=s$residual,
      status=if(best$numerically_eligible)'CANDIDATE_PENDING_HUMAN_REVIEW' else 'REJECTED_IDENTIFIABILITY',
      reasons=as.list(best$rejection_reasons),starts_converged=length(fits)),best$diagnostics)
    all_fits[[s$id]]<-best
  }
  write_pkpd_json(unname(rows),file.path(out,'comparison.json'))
  cat('FINISH',s$id,rows[[s$id]]$status,'\n');flush.console()
}
eligible<-names(all_fits)[vapply(all_fits,function(f)f$numerically_eligible,logical(1))]
order_ids<-eligible[order(vapply(all_fits[eligible],function(f)f$diagnostics$AIC,numeric(1)))]
cv_ids<-head(order_ids,2);cv<-list()
for(id in cv_ids) {
  f<-all_fits[[id]];folds<-list();errors<-numeric()
  animals<-unique(d$subject_id)
  cv_spec<-f[c('fixed_log_parameters','compartments','random_structure','residual')]
  fold_results<-map_fits(animals,function(animal,d,meta,model_spec) {
    train<-d[d$subject_id!=animal,,drop=FALSE];test<-d[d$subject_id==animal,,drop=FALSE]
    start<-setNames(exp(model_spec$fixed_log_parameters),sub('^log_','',names(model_spec$fixed_log_parameters)))
    refit<-tryCatch(fit_population_candidate(train,meta,model_spec$compartments,start,model_spec$random_structure,model_spec$residual),error=identity)
    if(inherits(refit,'error'))list(fold=list(status='FAILED',reason=conditionMessage(refit)),errors=numeric()) else {
      pred<-predict_population_candidate(refit,test);e<-log(test$concentration_mg_L)-log(pred)
      list(errors=e,fold=list(status='FITTED',n=nrow(test),RMSE_log=sqrt(mean(e^2)),
        warnings=refit$warnings,numerically_eligible=refit$numerically_eligible))
    }
  },d=d,meta=meta,model_spec=cv_spec)
  for(i in seq_along(animals)) {
    folds[[animals[i]]]<-fold_results[[i]]$fold;errors<-c(errors,fold_results[[i]]$errors)
  }
  complete<-all(vapply(folds,function(x)x$status=='FITTED',logical(1)))
  cv[[id]]<-list(folds=folds,folds_successful=sum(vapply(folds,function(x)x$status=='FITTED',logical(1))),
    RMSE_log=if(complete)sqrt(mean(errors^2)) else NULL,
    interpretation='Leave-one-animal-out typical prediction, eta=0; model-screened top-two only, not nested selection validation')
  write_pkpd_json(cv,file.path(out,'heldout_animal_validation.json'))
}
if(!is.null(cluster)){parallel::stopCluster(cluster);cluster<-NULL}
if(length(order_ids)) {
  best<-all_fits[[order_ids[1]]]
  plotted<-best$data
  png(file.path(out,'best_numerical_candidate_diagnostics.png'),width=1200,height=950,res=130)
  par(mfrow=c(2,2),mar=c(4,4,3,1))
  plot(best$predicted,plotted$concentration_mg_L,log='xy',pch=16,xlab='Conditional fitted (mg/L)',ylab='Observed (mg/L)',main=order_ids[1]);abline(0,1,lty=2)
  plot(plotted$time_h,as.numeric(residuals(best$fit,type='normalized')),pch=16,xlab='Time (h)',ylab='Normalized residual');abline(h=0,lty=2)
  qqnorm(as.numeric(residuals(best$fit,type='normalized')),pch=16);qqline(as.numeric(residuals(best$fit,type='normalized')))
  colors<-seq_along(unique(plotted$subject_id));plot(plotted$time_h,plotted$concentration_mg_L,log='y',pch=16,col=as.integer(factor(plotted$subject_id)),xlab='Time (h)',ylab='Concentration (mg/L)')
  for(animal in unique(plotted$subject_id)){ii<-which(plotted$subject_id==animal);lines(plotted$time_h[ii],best$predicted[ii],col=as.integer(factor(plotted$subject_id))[ii[1]])}
  dev.off()
}
write_pkpd_json(list(status='COMPLETED_PENDING_HUMAN_REVIEW',provenance=request$provenance,
  comparison=unname(rows),selection=list(numerical_lowest_AIC=if(length(order_ids))order_ids[1] else NULL,
    ranking_after_numerical_screen=as.list(order_ids),final_best_model=NULL,
    status='PENDING_RESIDUAL_AND_PREDICTIVE_REVIEW'),cross_validation=cv,
  comparison_basis='Same 102 concentrations; lognormal log-likelihood corrected by -sum(log(observed C)) before comparison with raw combined-error likelihood',
  exclusions=request$exclusions,human_review=list(decision='PENDING',approved_for_downstream_use=FALSE)),file.path(out,'output.json'))
capture.output(sessionInfo(),file=file.path(out,'sessionInfo.txt'))
cat('Population comparison completed\n')
}
main()
