# Exploratory mean-curve fitting only. No fabricated subjects or random effects.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==2)
suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(minpack.lm))
request <- read_json(args[1],simplifyVector=TRUE)
out <- args[2]; dir.create(out,recursive=TRUE,showWarnings=FALSE)
d <- request$records; nc <- request$compartments; route <- request$route
stopifnot(nc %in% 1:2,route %in% c('IV','SC','IP'),nrow(d)>5,
          all(is.finite(d$time_h)),all(d$time_h>0),all(d$concentration_mg_L>0),all(d$dose_mg_kg>0))
set.seed(request$seed)
conv_exp <- function(t,r,ka) {
  delta <- abs(ka-r)
  if(delta<1e-8)return(t*exp(-r*t))
  exp(-min(r,ka)*t)*(-expm1(-delta*t))/delta
}
curve <- function(t,dose,b) {
  p <- exp(b)
  if(route=='IV' && nc==1)return(dose*p[1]*exp(-p[2]*t))
  if(route=='IV' && nc==2)return(dose*(p[1]*exp(-(p[3]+p[4])*t)+p[2]*exp(-p[3]*t)))
  if(nc==1)return(dose*p[1]*exp(-p[2]*t)*(-expm1(-p[3]*t)))
  CL<-p[1];Vc<-p[2];Q<-p[3];Vp<-p[4];ka<-p[5]
  k10<-CL/Vc;k12<-Q/Vc;k21<-Q/Vp;s<-k10+k12+k21
  root<-sqrt(max(0,s*s-4*k10*k21));a<-(s+root)/2;b<-2*k10*k21/(s+root)
  dose*ka*((a-k21)/(Vc*(a-b))*conv_exp(t,a,ka)+(k21-b)/(Vc*(a-b))*conv_exp(t,b,ka))
}
parameter_names <- if(route=='IV') {
  if(nc==1)c('amplitude_per_dose','elimination_rate') else c('fast_amplitude_per_dose','slow_amplitude_per_dose','slow_rate','rate_gap')
} else if(nc==1)c('amplitude_per_dose','slow_rate','rate_gap') else c('CL_over_F_reported','Vc_over_F_reported','Q_over_F_reported','Vp_over_F_reported','ka')
np<-length(parameter_names); bnames<-paste0('b',seq_len(np))
profiles<-split(d,d$dose_mg_kg)
estimates<-lapply(profiles,function(z){
  z<-z[order(z$time_h),];tail<-tail(z,min(3,nrow(z)))
  slope<-as.numeric(coef(lm(log(concentration_mg_L)~time_h,tail))[2])
  k<-if(is.finite(slope)&&slope<0)-slope else 1/max(z$time_h)
  auc<-sum(diff(c(0,z$time_h))*(head(c(0,z$concentration_mg_L),-1)+z$concentration_mg_L)/2)+tail(z$concentration_mg_L,1)/k
  c(CL=z$dose_mg_kg[1]/auc,V=z$dose_mg_kg[1]/max(z$concentration_mg_L),k=k,
    peak=z$time_h[which.max(z$concentration_mg_L)])
})
st<-exp(rowMeans(log(do.call(cbind,estimates))))
base<-if(route=='IV'&&nc==1)c(1/st['V'],st['k']) else if(route=='IV')c(.5/st['V'],.5/st['V'],st['k'],2/max(st['peak'],.05)) else
  if(nc==1)c(2/st['V'],st['k'],3/max(st['peak'],.05)) else c(st['CL'],st['V'],st['CL'],st['V'],3/max(st['peak'],.05))
base<-setNames(log(as.numeric(base)),bnames)
starts<-c(list(base),lapply(seq_len(15),function(i)setNames(pmax(-10,pmin(10,base+runif(np,-2,2))),bnames)))
stopifnot(all(vapply(starts,function(x)identical(names(x),bnames)&&all(is.finite(x)),logical(1))))
write_json(list(method='Observed dose-normalized peaks, trapezoidal area and terminal slopes; seeded log perturbations',
  initial_log_values=starts,log_bounds=c(-12,12),seed=request$seed,published_parameters_used=FALSE),file.path(out,'initialization.json'),auto_unbox=TRUE,pretty=TRUE)
model_fun<-function(time_h,dose_mg_kg,...)curve(time_h,dose_mg_kg,unlist(list(...)))
results<-list(); attempt_log<-list()
for(error in c('lognormal','additive')) {
  lhs<-if(error=='lognormal')'log(concentration_mg_L)' else 'concentration_mg_L'
  rhs<-paste0('model_fun(time_h,dose_mg_kg,',paste(bnames,collapse=','),')')
  if(error=='lognormal')rhs<-paste0('log(',rhs,')')
  form<-as.formula(paste(lhs,'~',rhs));fits<-list()
  for(i in seq_along(starts)){
    warnings<-character()
    f<-tryCatch(withCallingHandlers(nlsLM(form,data=d,start=as.list(starts[[i]]),lower=rep(-12,np),upper=rep(12,np),
      control=nls.lm.control(maxiter=800,maxfev=10000),model=TRUE),warning=function(w){warnings<<-c(warnings,conditionMessage(w));invokeRestart('muffleWarning')}),error=identity)
    ok<-!inherits(f,'error')&&isTRUE(f$convInfo$isConv)
    attempt_log[[length(attempt_log)+1]]<-list(error_model=error,start=i,converged=ok,
      message=if(inherits(f,'error'))conditionMessage(f) else f$convInfo$stopMessage,warnings=warnings)
    if(ok)fits[[length(fits)+1]]<-f
  }
  id<-paste(request$analysis_id,paste0(nc,'C'),error,sep='_')
  if(!length(fits)) {results[[length(results)+1]]<-list(candidate_id=id,analysis_id=request$analysis_id,
    compartments=nc,error_model=error,status='ALL_STARTS_FAILED',converged=FALSE,attempted_starts=length(starts),converged_starts=0);next}
  f<-fits[[which.min(vapply(fits,deviance,numeric(1)))]]
  beta<-coef(f);pred<-curve(d$time_h,d$dose_mg_kg,beta)
  resid<-if(error=='lognormal')log(d$concentration_mg_L)-log(pred) else d$concentration_mg_L-pred
  n<-nrow(d);k<-np+1;sse<-sum(resid^2);sig<-sqrt(sse/n)
  # Full density of the same observed concentration values, including the
  # lognormal Jacobian. Additive and lognormal AIC are therefore comparable.
  ll<-sum(dnorm(resid,sd=sig,log=TRUE))-if(error=='lognormal')sum(log(d$concentration_mg_L)) else 0
  aic<--2*ll+2*k;bic<--2*ll+k*log(n)
  cov<-tryCatch(vcov(f),error=function(e)NULL)
  se<-if(is.null(cov))rep(NA_real_,np) else sqrt(diag(cov))
  estimates<-exp(beta);critical<-qt(.975,n-np)
  parameters<-data.frame(parameter=parameter_names,estimate=unname(estimates),SE=unname(estimates*se),
    RSE_percent=unname(100*se),CI95_lower=unname(exp(beta-critical*se)),CI95_upper=unname(exp(beta+critical*se)))
  parameters$unit<-ifelse(grepl('rate|^ka$',parameter_names),'1/h',
    ifelse(grepl('CL_|Q_',parameter_names),'L/h/kg on reported dose scale',
    ifelse(grepl('Vc_|Vp_',parameter_names),'L/kg on reported dose scale','(mg/L)/(reported mg/kg)')))
  eig<-if(!is.null(cov)&&all(is.finite(cov)))eigen(cov,symmetric=TRUE,only.values=TRUE)$values else NA_real_
  pd<-all(is.finite(eig))&&min(eig)>0
  correlation<-if(pd)max(abs(cov2cor(cov)[upper.tri(cov)])) else NA_real_
  boundary<-any(abs(beta)>11.99)
  finite_ci<-all(is.finite(as.matrix(parameters[,c('estimate','SE','RSE_percent','CI95_lower','CI95_upper')])))
  reasons<-character()
  if(!pd)reasons<-c(reasons,'Covariance unavailable or not positive definite')
  if(!finite_ci)reasons<-c(reasons,'At least one local parameter interval is nonfinite')
  if(boundary)reasons<-c(reasons,'Parameter at numerical bound')
  warnings<-c('Exploratory fit of reported means; likelihood assumes independent mean-level errors.',
    'Wald intervals are conditional on the curve/error model; they exclude digitization and biological uncertainty.',
    'No interindividual random effects or qualified human translation.')
  if(is.finite(correlation)&&correlation>.95)warnings<-c(warnings,'Parameter correlation exceeds 0.95; inspect practical identifiability (warning, not a universal cutoff).')
  if(route!='IV')warnings<-c(warnings,'Absorption/disposition labels and F are not identified by extravascular data alone; apparent parameters are conditional.')
  folder<-file.path(out,error);dir.create(folder,showWarnings=FALSE)
  derived_fun<-function(b){p<-unname(exp(b))
    if(route=='IV'&&nc==1)return(c(CL_L_h_kg=p[2]/p[1],V_L_kg=1/p[1],half_life_h=log(2)/p[2]))
    if(route=='IV'){
      a<-p[1];bb<-p[2];beta<-p[3];alpha<-beta+p[4];vc<-1/(a+bb)
      k21<-(a*beta+bb*alpha)/(a+bb);q<-vc*(alpha+beta-k21-alpha*beta/k21);vp<-q/k21
      return(c(CL_L_h_kg=1/(a/alpha+bb/beta),Vc_L_kg=vc,Q_L_h_kg=q,Vp_L_kg=vp,Vss_L_kg=vc+vp,terminal_half_life_h=log(2)/beta))
    }
    if(nc==1){fast<-p[2]+p[3];return(c(CL_over_F_reported=p[2]*fast/(p[1]*p[3]),
      V_over_F_if_fast_absorption=fast/(p[1]*p[3]),V_over_F_if_slow_absorption=p[2]/(p[1]*p[3]),terminal_half_life_h=log(2)/p[2]))}
    c(CL_over_F_reported=p[1],Vc_over_F_reported=p[2],Q_over_F_reported=p[3],Vp_over_F_reported=p[4],Vss_over_F_reported=p[2]+p[4],ka=p[5])
  }
  derived<-derived_fun(beta)
  grad<-sapply(seq_along(beta),function(j){lo<-hi<-beta;lo[j]<-lo[j]-1e-5;hi[j]<-hi[j]+1e-5;(log(derived_fun(hi))-log(derived_fun(lo)))/2e-5})
  derived_se_log<-if(pd&&all(is.finite(grad)))sqrt(pmax(0,diag(grad%*%cov%*%t(grad)))) else rep(NA_real_,length(derived))
  derived_table<-data.frame(parameter=names(derived),estimate=unname(derived),SE=unname(derived*derived_se_log),
    RSE_percent=unname(100*derived_se_log),CI95_lower=unname(exp(log(derived)-critical*derived_se_log)),
    CI95_upper=unname(exp(log(derived)+critical*derived_se_log)),
    interpretation='Conditional mean-curve estimate; dose/analyte metadata and input model must hold. Not individual PK variability.')
  write.csv(derived_table,file.path(folder,'conditional_pk_parameters.csv'),row.names=FALSE)
  write.csv(parameters,file.path(folder,'parameters.csv'),row.names=FALSE)
  csv_data<-d
  for(column in names(csv_data))if(is.list(csv_data[[column]]))csv_data[[column]]<-vapply(csv_data[[column]],function(v)toJSON(v,auto_unbox=FALSE),character(1))
  write.csv(data.frame(csv_data,predicted_mg_L=pred,residual_fit_scale=resid),file.path(folder,'predictions.csv'),row.names=FALSE)
  if(!is.null(cov))write.csv(cov,file.path(folder,'covariance_log_parameters.csv'))
  saveRDS(f,file.path(folder,'fit.rds'))
  r2<-function(y,p)1-sum((y-p)^2)/sum((y-mean(y))^2)
  profile_diagnostics<-do.call(rbind,lapply(split(seq_len(n),d$dose_mg_kg),function(ix){
    data.frame(dose_mg_kg=d$dose_mg_kg[ix[1]],n=length(ix),R2_raw=r2(d$concentration_mg_L[ix],pred[ix]),
      mean_residual_raw=mean(d$concentration_mg_L[ix]-pred[ix]),
      mean_log_observed_over_predicted=mean(log(d$concentration_mg_L[ix]/pred[ix])),
      residual_time_correlation=if(length(ix)>2&&sd(resid[ix])>0)cor(d$time_h[ix],resid[ix]) else NA_real_)
  }))
  write.csv(profile_diagnostics,file.path(folder,'profile_diagnostics.csv'),row.names=FALSE)
  metric<-list(candidate_id=id,analysis_id=request$analysis_id,compartments=nc,error_model=error,
    status=if(length(reasons))'NUMERICALLY_FITTED_DIAGNOSTIC_CONCERNS' else 'EXPLORATORY_CANDIDATE_PENDING_REVIEW',
    converged=TRUE,n_observations=n,n_parameters=k,logLik=ll,minus2logLik=-2*ll,AIC=aic,BIC=bic,
    AICc=if(n>k+1)aic+2*k*(k+1)/(n-k-1) else NA_real_,sigma_MLE=sig,
    R2_raw=r2(d$concentration_mg_L,pred),R2_log=r2(log(d$concentration_mg_L),log(pred)),
    RMSE_raw=sqrt(mean((d$concentration_mg_L-pred)^2)),RMSE_log=sqrt(mean((log(d$concentration_mg_L)-log(pred))^2)),
    MAE_raw=mean(abs(d$concentration_mg_L-pred)),mean_residual_raw=mean(d$concentration_mg_L-pred),
    covariance_positive_definite=pd,covariance_condition=if(pd)max(eig)/min(eig) else NA_real_,
    max_parameter_correlation=correlation,max_RSE_percent=max(parameters$RSE_percent),parameter_at_bound=boundary,
    finite_local_intervals=finite_ci,numerically_eligible=length(reasons)==0,
    converged_starts=length(fits),attempted_starts=length(starts),reasons=as.list(reasons),warnings=as.list(warnings),
    parameters=parameters,conditional_pk_parameters=derived_table,profile_diagnostics=profile_diagnostics,
    likelihood='Concentration density with Gaussian or lognormal mean-level residuals, including all constants and Jacobian',
    prediction_statistic=if(error=='lognormal')'Conditional median of reported means' else 'Conditional expectation of reported means',
    observation_unit=request$observation_unit,clinical_or_biological_validation=FALSE,
    CV_status='NOT_ESTABLISHED: independently identified animals/cohorts unavailable; no fabricated animal folds')
  results[[length(results)+1]]<-metric
  png(file.path(folder,'fit_and_diagnostics.png'),width=1400,height=1000,res=130)
  par(mfrow=c(2,2),mar=c(4.3,4.3,3,1));cols<-seq_along(profiles)+1
  plot_grids<-lapply(profiles,function(z){
    grid<-seq(if(route=='IV')0 else max(.001,min(z$time_h)/10),max(z$time_h),length.out=500)
    list(t=grid,c=curve(grid,z$dose_mg_kg[1],beta))
  })
  y_all<-c(d$concentration_mg_L,unlist(lapply(plot_grids,function(z)z$c)))
  for(logy in c('', 'y')){
    plot(d$time_h,d$concentration_mg_L,log=logy,type='n',xlim=c(0,max(d$time_h)),
      ylim=if(logy=='y')range(y_all[y_all>0&is.finite(y_all)]) else c(0,max(y_all[is.finite(y_all)])),
      xlab='Time (h)',ylab='Reported concentration (mg/L)',main=paste(nc,'compartment',route,error,if(logy=='y')'semilog' else 'linear'))
    for(j in seq_along(profiles)){z<-profiles[[j]];points(z$time_h,z$concentration_mg_L,col=cols[j],pch=16)
      lines(plot_grids[[j]]$t,plot_grids[[j]]$c,col=cols[j],lwd=2)}
    legend('topright',paste(names(profiles),'reported mg/kg'),col=cols,pch=16,bty='n',cex=.7)
  }
  plot(pred,d$concentration_mg_L,xlab='Predicted concentration',ylab='Observed concentration',main='Observed vs predicted',pch=16);abline(0,1,col='grey')
  plot(d$time_h,resid,xlab='Time (h)',ylab=paste(error,'residual'),main='Residuals vs time',pch=16);abline(h=0,col='grey');dev.off()
  grid_rows<-do.call(rbind,lapply(profiles,function(z){t<-seq(0,max(z$time_h),length.out=501);data.frame(time_h=t,dose_mg_kg=z$dose_mg_kg[1],predicted_mg_L=curve(t,z$dose_mg_kg[1],beta))}))
  write.csv(grid_rows,file.path(folder,'fitted_curves.csv'),row.names=FALSE)
  exposures<-do.call(rbind,lapply(profiles,function(z){
    dose<-z$dose_mg_kg[1];end<-max(z$time_h)
    auc<-integrate(function(t)curve(t,dose,beta),0,end,rel.tol=1e-7)$value
    aucinf<-tryCatch(integrate(function(t)curve(t,dose,beta),0,Inf,rel.tol=1e-7)$value,error=function(e)NA_real_)
    peak<-if(route=='IV')list(minimum=0,objective=-curve(0,dose,beta)) else optimize(function(t)-curve(t,dose,beta),c(0,end))
    data.frame(dose_mg_kg=dose,window_start_h=0,window_end_h=end,AUC_window_mg_h_L=auc,AUC_inf_conditional=aucinf,
      fraction_AUC_extrapolated=1-auc/aucinf,Cmax_within_window_mg_L=-peak$objective,Tmax_within_window_h=peak$minimum,
      curve_statistic=metric$prediction_statistic,free_exposure_computed=FALSE)
  }))
  write.csv(exposures,file.path(folder,'exposure_summary.csv'),row.names=FALSE)
}
write_json(attempt_log,file.path(out,'optimization_attempts.json'),auto_unbox=TRUE,pretty=TRUE,na='null')
write_json(list(status='NUMERICAL_FITS_COMPLETE_PENDING_REVIEW',analysis_id=request$analysis_id,
  species='mouse',compartments=nc,engine='R minpack.lm::nlsLM',random_effects=FALSE,
  source_refs=request$source_refs,rows=results,R_version=R.version.string,
  minpack_lm_version=as.character(packageVersion('minpack.lm')),session_info=capture.output(sessionInfo())),
  file.path(out,'numerical_results.json'),auto_unbox=TRUE,pretty=TRUE,na='null',digits=15)
cat('Completed',request$analysis_id,nc,'compartment; no scientific model accepted.\n')
