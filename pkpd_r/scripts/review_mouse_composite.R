args<-commandArgs(trailingOnly=TRUE)
if(length(args)!=2)stop('Expected input.json and new output directory')
script<-normalizePath(sub('^--file=','',grep('^--file=',commandArgs(),value=TRUE)[1]),mustWork=TRUE)
base<-dirname(dirname(script));source(file.path(base,'load.R'),encoding='UTF-8')
source(file.path(base,'modules/shared.R'),encoding='UTF-8')
request<-jsonlite::read_json(args[1],simplifyVector=FALSE);raw<-records_frame(request$records);out<-args[2]
if(dir.exists(out))stop('Use a new output directory')
dir.create(out,recursive=TRUE)
stopifnot(request$metadata$species=='mouse',request$metadata$route=='IP',request$metadata$matrix=='plasma',
  all(raw$status=='QUANTIFIED'),all(raw$concentration_mg_L>0),all(raw$dose_mg_kg==5))
groups<-split(raw,raw$time_h)
d<-do.call(rbind,lapply(groups,function(z)data.frame(time_h=z$time_h[1],
  concentration_mg_L=mean(z$concentration_mg_L),n_source_slots=nrow(z),
  source_record_ids=paste(z$record_id,collapse=';'))))
d<-d[order(d$time_h),];rownames(d)<-NULL
utils::write.csv(d,file.path(out,'time_summary_input.csv'),row.names=FALSE)
# First-order input is a working assumption for IP, not SC metadata substitution.
# One-compartment curve is parameterized by ordered rates; flip-flop labels remain unresolved.
one_curve<-function(t,log_A,log_slow,log_gap){
  slow<-exp(log_slow);fast<-slow+exp(log_gap)
  exp(log_A)*exp(-slow*t)*(-expm1(-(fast-slow)*t))
}
conv_exp<-function(t,r,ka){
  delta<-abs(ka-r)
  if(delta<1e-8)return(t*exp(-r*t))
  exp(-min(r,ka)*t)*(-expm1(-delta*t))/delta
}
two_curve<-function(t,log_CL_F,log_Vc_F,log_Q_F,log_Vp_F,log_ka){
  CL<-exp(log_CL_F);Vc<-exp(log_Vc_F);Q<-exp(log_Q_F);Vp<-exp(log_Vp_F);ka<-exp(log_ka)
  k10<-CL/Vc;k12<-Q/Vc;k21<-Q/Vp;s<-k10+k12+k21
  root<-sqrt(max(0,s*s-4*k10*k21));a<-(s+root)/2;b<-2*k10*k21/(s+root)
  5*ka*((a-k21)/(Vc*(a-b))*conv_exp(t,a,ka)+(k21-b)/(Vc*(a-b))*conv_exp(t,b,ka))
}
rows<-list();models<-list();logs<-list()
for(nc in 1:2){
  key<-paste0('MOUSE_IP_',nc,'C_FO_COMPOSITE')
  starts<-if(nc==1)lapply(c(2,5,10),function(k)c(log_A=log(20),log_slow=log(.5),log_gap=log(k))) else
    list(log(c(CL_F=.17,Vc_F=.25,Q_F=.05,Vp_F=.1,ka=4)),
         log(c(CL_F=.17,Vc_F=.1,Q_F=.3,Vp_F=.3,ka=6)),
         log(c(CL_F=.2,Vc_F=.3,Q_F=.1,Vp_F=.5,ka=10)),
         log(c(CL_F=.18,Vc_F=.2,Q_F=.02,Vp_F=.1,ka=2)))
  if(nc==2)starts<-lapply(starts,function(x)setNames(x,paste0('log_',names(x))))
  formula<-if(nc==1)log(concentration_mg_L)~log(one_curve(time_h,log_A,log_slow,log_gap)) else
    log(concentration_mg_L)~log(two_curve(time_h,log_CL_F,log_Vc_F,log_Q_F,log_Vp_F,log_ka))
  fits<-list()
  for(i in seq_along(starts)){
    x<-tryCatch(capture_fit(minpack.lm::nlsLM(formula,data=d,start=as.list(starts[[i]]),
      lower=rep(-12,length(starts[[i]])),upper=rep(12,length(starts[[i]])),
      control=minpack.lm::nls.lm.control(maxiter=400),model=TRUE)),error=identity)
    ok<-!inherits(x,'error') && isTRUE(x$value$convInfo$isConv)
    logs[[paste(key,i,sep=':')]]<-list(status=if(ok)'CONVERGED' else 'FAILED_NUMERICAL_START',
      reason=if(inherits(x,'error'))conditionMessage(x) else if(!ok)'Did not converge' else NULL)
    if(ok)fits[[length(fits)+1]]<-x
  }
  if(!length(fits)){rows[[key]]<-list(candidate=key,status='REJECTED_ALL_STARTS_FAILED');next}
  best<-fits[[which.min(vapply(fits,function(x)AIC(x$value),numeric(1)))]];f<-best$value
  pred<-exp(as.numeric(predict(f)));v<-tryCatch(vcov(f),error=function(e)NULL)
  p<-tryCatch(parameter_table(coef(f),v,rep(TRUE,length(coef(f))),.95,df.residual(f)),error=function(e)NULL)
  maxcorr<-if(is.null(v))NA_real_ else max(abs(cov2cor(v)[upper.tri(v)]))
  problems<-character()
  if(is.null(p) || any(!is.finite(as.matrix(p[c('estimate','SE','CI_lower','CI_upper')]))))problems<-c(problems,'Parameter interval unavailable or nonfinite')
  if(nc==2 && (is.na(maxcorr)||maxcorr>.95))problems<-c(problems,'Catalog: parameter correlation above 0.95')
  if(any(abs(coef(f))>11.9))problems<-c(problems,'Parameter at declared numerical bound')
  dg<-fit_diagnostics(f,d$concentration_mg_L,pred,TRUE)
  # These scores describe nine time summaries; unknown cross-time dependence is not resolved.
  rows[[key]]<-c(list(candidate=key,status=if(length(problems))'REJECTED_IDENTIFIABILITY' else 'DESCRIPTIVE_CANDIDATE_PENDING_REVIEW',
    reasons=as.list(problems),n_time_summaries=nrow(d),n_raw_slots=nrow(raw),independent_animals='NOT_FOUND',
    max_parameter_correlation=maxcorr,max_RSE_percent=if(!is.null(p))max(p$RSE_percent) else NULL,
    R2_log=1-sum((log(d$concentration_mg_L)-log(pred))^2)/sum((log(d$concentration_mg_L)-mean(log(d$concentration_mg_L)))^2)),dg)
  folder<-file.path(out,'models',key);dir.create(folder,recursive=TRUE)
  saveRDS(f,file.path(folder,'model.rds'));if(!is.null(p))utils::write.csv(p,file.path(folder,'parameters.csv'),row.names=FALSE)
  utils::write.csv(data.frame(d,predicted=pred),file.path(folder,'predictions.csv'),row.names=FALSE)
  write_pkpd_json(list(summary=rows[[key]],parameters=p,warnings=best$warnings),file.path(folder,'result.json'))
  models[[key]]<-list(fit=f,nc=nc)
}
write_pkpd_json(logs,file.path(out,'optimization_starts.json'))
eligible<-names(rows)[vapply(rows,function(x)x$status=='DESCRIPTIVE_CANDIDATE_PENDING_REVIEW',logical(1))]
winner<-if(length(eligible))eligible[which.min(vapply(rows[eligible],function(x)x$AICc,numeric(1)))] else NULL
png(file.path(out,'mouse_composite_fits.png'),width=1000,height=760,res=120)
plot(d$time_h,d$concentration_mg_L,log='y',pch=16,xlab='Time (h)',ylab='Reported plasma concentration (mg/L)',main='Mouse IP: time-summary descriptive fits')
points(raw$time_h,raw$concentration_mg_L,pch=1,col='#77777780')
grid<-data.frame(time_h=seq(.01,max(d$time_h),length.out=300))
for(j in seq_along(models))lines(grid$time_h,exp(predict(models[[j]]$fit,grid)),col=c('#2371A0','#B85B27')[j],lty=j,lwd=2)
legend('topright',c('Time means','1 compartment + input','2 compartments + input'),pch=c(16,NA,NA),lty=c(NA,1,2),col=c('black','#2371A0','#B85B27'),bty='n');dev.off()
write_pkpd_json(list(status='DESCRIPTIVE_COMPLETED_PENDING_HUMAN_REVIEW',provenance=request$provenance,
  source_metadata=request$metadata,comparison=unname(rows),numerical_best_after_screen=winner,
  limitations=list('Concentration basis remains NOT_FOUND; no total/free reassignment',
    'Time summaries are not animal identities; no IIV or biological precision inference',
    'Conditional log-Gaussian score on nine means; cross-time dependence unknown',
    'IP first-order input is an exploratory assumption; absorption/disposition flip-flop is not resolved',
    'One-compartment fit uses amplitude and ordered rates; two-compartment apparent parameters are conditional on unspecified reported concentration scale',
    'No human translation or index calculation from these curves'),
  human_review=list(decision='PENDING',approved_for_downstream_use=FALSE)),file.path(out,'output.json'))
cat('Mouse descriptive curve comparison completed\n')
