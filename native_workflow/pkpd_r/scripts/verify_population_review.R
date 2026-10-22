args<-commandArgs(trailingOnly=TRUE)
source('pkpd_r/load.R',encoding='UTF-8');source('pkpd_r/R/population_candidates.R',encoding='UTF-8')
source('pkpd_r/modules/shared.R',encoding='UTF-8')
run<-args[1];out<-args[2];if(dir.exists(out))stop('Use a new verification directory');dir.create(out,recursive=TRUE)
request<-jsonlite::read_json(file.path(run,'input.json'),simplifyVector=FALSE)
source_data<-records_frame(request$records)
result<-jsonlite::read_json(file.path(run,'results/output.json'),simplifyVector=FALSE)
checks<-list()
for(row in result$comparison){
  if(is.null(row$AIC))next
  obj<-readRDS(file.path(run,'results/models',row$candidate,'model.rds'));d<-obj$data
  stopifnot(setequal(d$record_id,source_data$record_id))
  matched<-match(d$record_id,source_data$record_id)
  stopifnot(max(abs(d$concentration_mg_L-source_data$concentration_mg_L[matched]))==0)
  beta<-coef(obj$fit);idx<-match(as.character(d$subject_id),rownames(beta))
  manual<-iv_population_concentration(d$time_h,d$dose_mg_kg,d$dose_time_h,d$duration_h,
    beta$log_CL[idx],beta$log_Vc[idx],if(obj$compartments==2)beta$log_Q[idx] else NULL,
    if(obj$compartments==2)beta$log_Vp[idx] else NULL)
  stopifnot(max(abs(manual-obj$predicted))<1e-8)
  ll<-logLik(obj$fit);k<-attr(ll,'df');adjusted<-as.numeric(ll)-if(obj$residual=='lognormal')sum(log(d$concentration_mg_L)) else 0
  stopifnot(abs(row$AIC-(-2*adjusted+2*k))<1e-8,abs(row$BIC-(-2*adjusted+k*log(nrow(d))))<1e-8)
  checks[[row$candidate]]<-list(status='PASSED',n=nrow(d),max_prediction_difference=max(abs(manual-obj$predicted)))
}
id<-result$selection$numerical_lowest_AIC;best<-readRDS(file.path(run,'results/models',id,'model.rds'));d<-best$data
png(file.path(out,'rat_population_diagnostics.png'),width=1300,height=1050,res=140)
par(mfrow=c(2,2),mar=c(4.2,4.2,3,1))
plot(best$predicted,d$concentration_mg_L,log='xy',pch=16,xlab='Conditional fitted (mg/L)',ylab='Observed (mg/L)',main=id);abline(0,1,lty=2)
plot(d$time_h,as.numeric(residuals(best$fit,type='normalized')),pch=16,xlab='Time (h)',ylab='Normalized residual',main='Aligned by source record ID');abline(h=0,lty=2)
qqnorm(as.numeric(residuals(best$fit,type='normalized')),pch=16);qqline(as.numeric(residuals(best$fit,type='normalized')))
plot(d$time_h,d$concentration_mg_L,log='y',pch=16,col=as.integer(d$subject_id),xlab='Time (h)',ylab='Concentration (mg/L)',main='Individual conditional curves')
for(animal in unique(d$subject_id)){ii<-which(d$subject_id==animal);lines(d$time_h[ii],best$predicted[ii],col=as.integer(d$subject_id)[ii[1]])};dev.off()
write_pkpd_json(list(status='PASSED',candidate_checks=checks,
  figure_correction='Uses fitted-object row order for observed/predicted pairing. Supersedes original population diagnostic PNG; numerical estimates unchanged.',
  selection=result$selection),file.path(out,'verification.json'))
cat('All saved population likelihoods, row alignment and predictions verified\n')
