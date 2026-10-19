# Vectorized finite-infusion models for nlme: parameters may vary by animal.
iv_population_concentration <- function(time_h,dose_mg_kg,dose_time_h,duration_h,
                                        log_CL,log_Vc,log_Q=NULL,log_Vp=NULL) {
  CL<-exp(log_CL);Vc<-exp(log_Vc);elapsed<-time_h-dose_time_h
  component<-function(rate,amp) {
    t<-pmax(elapsed,0)
    ifelse(elapsed<0,0,amp*dose_mg_kg/duration_h*
      (-expm1(-rate*pmin(t,duration_h)))/rate*exp(-rate*pmax(t-duration_h,0)))
  }
  if(is.null(log_Q)) return(component(CL/Vc,1/Vc))
  Q<-exp(log_Q);Vp<-exp(log_Vp)
  k10<-CL/Vc;k12<-Q/Vc;k21<-Q/Vp;total<-k10+k12+k21
  root<-sqrt(pmax(0,total^2-4*k10*k21))
  alpha<-(total+root)/2;beta<-2*k10*k21/(total+root)
  component(alpha,(alpha-k21)/(Vc*(alpha-beta)))+
    component(beta,(k21-beta)/(Vc*(alpha-beta)))
}

fit_population_candidate <- function(data,meta,compartments,start,random_structure='diag_clv',
                                     residual='lognormal',ci_level=.95) {
  internal<-meta;internal$dose_unit<-'mg'
  data<-validate_pk_data(data,internal,TRUE)
  stopifnot(meta$dose_unit=='mg/kg',meta$regimen_type=='single_dose',compartments %in% 1:2,
    all(data$concentration_mg_L>0),all(data$duration_h>0),all(data$time_h>=data$dose_time_h),
    residual %in% c('lognormal','combined'),random_structure %in% c('diag_clv','cor_clv','diag_all'))
  parameters<-if(compartments==1)c('CL','Vc') else c('CL','Vc','Q','Vp')
  stopifnot(setequal(names(start),parameters),all(start>0),length(unique(data$subject_id))>=3)
  for(d in split(data,data$subject_id)) stopifnot(nrow(unique(d[c('dose_mg_kg','dose_time_h','duration_h')]))==1)
  pn<-paste0('log_',parameters);rn<-if(random_structure=='diag_all')pn else c('log_CL','log_Vc')
  data$subject_id<-factor(data$subject_id)
  expression<-paste0('iv_population_concentration(time_h,dose_mg_kg,dose_time_h,duration_h,',paste(pn,collapse=','),')')
  model<-as.formula(paste(if(residual=='lognormal')'log(concentration_mg_L)' else 'concentration_mg_L','~',
    if(residual=='lognormal')paste0('log(',expression,')') else expression),env=environment())
  fixed<-as.formula(paste(paste(pn,collapse='+'),'~1'))
  rf<-as.formula(paste(paste(rn,collapse='+'),'~1'))
  random<-if(random_structure=='cor_clv')nlme::pdSymm(rf) else nlme::pdDiag(rf)
  # Fix sigma for varConstProp, so two scale parameters are identifiable.
  weights<-if(residual=='combined')nlme::varConstProp(const=.03,prop=.2,form=~fitted(.)) else NULL
  control<-nlme::nlmeControl(maxIter=200,pnlsMaxIter=40,msMaxIter=200,
    returnObject=FALSE,sigma=if(residual=='combined')1 else NULL)
  captured<-capture_fit(nlme::nlme(model,data=data,fixed=fixed,random=random,groups=~subject_id,
    weights=weights,start=setNames(log(start[parameters]),pn),method='ML',na.action=stats::na.fail,control=control))
  f<-captured$value;b<-nlme::fixef(f);cov<-vcov(f)
  tab<-parameter_table(b,cov,rep(TRUE,length(b)),ci_level)
  if(compartments==1)tab$parameter[tab$parameter=='Vc']<-'V'
  tab$unit<-ifelse(tab$parameter %in% c('CL','Q'),'L/h/kg','L/kg')
  predicted<-as.numeric(predict(f,level=1));if(residual=='lognormal')predicted<-exp(predicted)
  typical<-as.numeric(predict(f,level=0));if(residual=='lognormal')typical<-exp(typical)
  ll<-logLik(f);k<-attr(ll,'df');n<-nrow(data)
  # Put both residual families on the same observed-concentration density scale.
  jacobian<-if(residual=='lognormal')sum(log(data$concentration_mg_L)) else 0
  common_ll<-as.numeric(ll)-jacobian;aic<- -2*common_ll+2*k
  maxcorr<-max(abs(cov2cor(cov)[upper.tri(cov)]))
  omega<-nlme::pdMatrix(f$modelStruct$reStruct[[1]])*f$sigma^2
  re_cor<-cov2cor(omega);max_re_corr<-max(abs(re_cor[upper.tri(re_cor)]))
  problems<-character()
  if(any(!is.finite(as.matrix(tab[c('estimate','SE','CI_lower','CI_upper')]))))problems<-c(problems,'Nonfinite parameter interval')
  if(any(eigen(cov,symmetric=TRUE,only.values=TRUE)$values<=0))problems<-c(problems,'Fixed-effect covariance is not positive definite')
  if(!is.matrix(f$apVar) || any(!is.finite(f$apVar)) || any(eigen(f$apVar,symmetric=TRUE,only.values=TRUE)$values<=0))
    problems<-c(problems,'Variance-parameter uncertainty unavailable or non-positive definite')
  if(compartments==2 && maxcorr>.95)problems<-c(problems,'Catalog: fixed-parameter correlation above 0.95')
  if(max_re_corr>.995)problems<-c(problems,'Random-effect correlation at numerical boundary (>0.995)')
  if(any(sqrt(diag(omega))<1e-4))problems<-c(problems,'Random-effect SD near numerical zero (<1e-4)')
  normalized<-as.numeric(residuals(f,type='normalized'))
  time_means<-aggregate(normalized,list(time_h=data$time_h),mean)
  names(time_means)[2]<-'mean_normalized_residual'
  # Descriptive flag only; does not masquerade as a formal residual-bias test.
  residual_flag<-any(abs(time_means$mean_normalized_residual)>.5)
  diag<-list(n_observations=n,n_subjects=length(unique(data$subject_id)),n_parameters=k,
    native_log_likelihood=as.numeric(ll),native_likelihood_scale=if(residual=='lognormal')'log concentration' else 'concentration',
    log_jacobian_subtracted=jacobian,log_likelihood_concentration=common_ll,AIC=aic,BIC=-2*common_ll+k*log(n),
    AICc_descriptive=aic+2*k*(k+1)/(n-k-1),
    AICc_limit='Observation-count correction is descriptive, not a validated small-cluster correction for NLME',
    R2_log_conditional=1-sum((log(data$concentration_mg_L)-log(predicted))^2)/sum((log(data$concentration_mg_L)-mean(log(data$concentration_mg_L)))^2),
    RMSE_log_conditional=sqrt(mean((log(data$concentration_mg_L)-log(predicted))^2)),
    max_fixed_parameter_correlation=maxcorr,max_random_effect_correlation=max_re_corr,
    max_RSE_percent=max(tab$RSE_percent),residual_time_pattern_flag=residual_flag,
    flag_definition='Any sampling-time mean normalized residual above 0.5 in absolute value; descriptive review trigger only')
  structure(list(type='population_candidate',fit=f,data=data,meta=meta,compartments=compartments,
    random_structure=random_structure,residual=residual,parameters=tab,fixed_log_parameters=b,
    covariance_log_parameters=cov,omega=omega,random_effects=nlme::ranef(f),predicted=predicted,typical=typical,
    diagnostics=diag,time_residual_summary=time_means,warnings=captured$warnings,
    rejection_reasons=problems,numerically_eligible=!length(problems)),class='pkpd_fit')
}

predict_population_candidate <- function(object,newdata) {
  b<-object$fixed_log_parameters
  iv_population_concentration(newdata$time_h,newdata$dose_mg_kg,newdata$dose_time_h,newdata$duration_h,
    b[['log_CL']],b[['log_Vc']],if(object$compartments==2)b[['log_Q']] else NULL,
    if(object$compartments==2)b[['log_Vp']] else NULL)
}
