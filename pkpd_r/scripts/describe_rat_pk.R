# Inspect saved fitted objects; this does not refit or approve the model.
args <- commandArgs(trailingOnly=TRUE)
if(length(args)!=2) stop('Expected previous rat run and a new output directory')
script <- normalizePath(sub('^--file=','',grep('^--file=',commandArgs(),value=TRUE)[1]),mustWork=TRUE)
source(file.path(dirname(dirname(script)),'load.R'),encoding='UTF-8')
run <- normalizePath(args[1],mustWork=TRUE);out <- args[2]
if(dir.exists(out)) stop('Use a new output directory')
dir.create(out,recursive=TRUE)
object <- readRDS(file.path(run,'results/population_1cpt/model.rds'))
fit <- object$fit
stopifnot(inherits(fit,'nlme'),fit$method=='ML')
fixed <- nlme::fixef(fit);eta <- nlme::ranef(fit)
omega <- nlme::pdMatrix(fit$modelStruct$reStruct[[1]]) * fit$sigma^2
variability <- data.frame(parameter=c('CL','V','residual'),
  log_variance=c(diag(omega),fit$sigma^2),log_SD=c(sqrt(diag(omega)),fit$sigma),
  CV_percent=100*sqrt(expm1(c(diag(omega),fit$sigma^2))))
individual <- data.frame(subject_id=rownames(eta),eta_log_CL=eta$log_CL,eta_log_V=eta$log_V,
  CL_L_h_kg=exp(fixed[['log_CL']]+eta$log_CL),V_L_kg=exp(fixed[['log_V']]+eta$log_V))
d <- object$data;row <- match(as.character(d$subject_id),individual$subject_id)
rate <- individual$CL_L_h_kg[row]/individual$V_L_kg[row]
manual <- d$dose_mg_kg/d$duration_h/individual$CL_L_h_kg[row]*
  (-expm1(-rate*d$duration_h))*exp(-rate*(d$time_h-d$dose_time_h-d$duration_h))
stopifnot(max(abs(manual-object$predicted))<1e-10)
typical <- predict_population_pk_infusion_per_kg(object,d,FALSE)
diagnostics <- data.frame(subject_id=d$subject_id,time_h=d$time_h,observed=d$concentration_mg_L,
  conditional_predicted=object$predicted,typical_predicted=typical,
  log_residual=log(d$concentration_mg_L)-log(object$predicted),
  normalized_residual=as.numeric(residuals(fit,type='normalized')))
utils::write.csv(variability,file.path(out,'variance_components.csv'),row.names=FALSE)
utils::write.csv(individual,file.path(out,'conditional_rat_parameters.csv'),row.names=FALSE)
utils::write.csv(diagnostics,file.path(out,'predictions_residuals.csv'),row.names=FALSE)
utils::write.csv(object$parameters,file.path(out,'population_parameters.csv'),row.names=FALSE)
starts <- lapply(list.files(file.path(run,'results/models'),pattern='_1cpt$',full.names=TRUE),
  function(p)readRDS(file.path(p,'model.rds'))$theta[c('CL','V')])
initial <- exp(rowMeans(log(do.call(cbind,starts))))
control <- nlme::nlmeControl(maxIter=200,pnlsMaxIter=40,msMaxIter=200,returnObject=FALSE)
png(file.path(out,'population_diagnostics.png'),width=1300,height=1100,res=140)
par(mfrow=c(2,2),mar=c(4.5,4.5,2.5,1))
plot(typical,d$concentration_mg_L,log='xy',pch=16,col='#2371A080',xlab='Typical prediction (mg/L)',ylab='Observed (mg/L)',main='Typical population curve');abline(0,1,lty=2)
plot(object$predicted,d$concentration_mg_L,log='xy',pch=16,col='#2371A080',xlab='Conditional prediction (mg/L)',ylab='Observed (mg/L)',main='Rat-specific conditional fit');abline(0,1,lty=2)
plot(d$time_h,diagnostics$normalized_residual,pch=16,col='#2371A080',xlab='Time (h)',ylab='Normalized log residual',main='Residuals by time');abline(h=0,lty=2)
qqnorm(diagnostics$normalized_residual,pch=16,col='#2371A080',main='Residual normal Q-Q');qqline(diagnostics$normalized_residual)
dev.off()
capture.output(sessionInfo(),file=file.path(out,'inspection_sessionInfo.txt'))
write_pkpd_json(list(status='INSPECTED_PENDING_HUMAN_REVIEW',refitted=FALSE,
  population=list(object_class=class(fit),model_type=object$type,method=fit$method,outer_iterations=fit$numIter,
    structural_model='One compartment; linear elimination; single finite IV infusion; mass-normalized parameters',
    input=list(dose_mg_kg=unique(d$dose_mg_kg),duration_h=unique(d$duration_h),
      concentration_basis=object$meta$concentration_basis,time_range_h=range(d$time_h),n_subjects=length(unique(d$subject_id)),n_observations=nrow(d)),
    equation_post_infusion='C_i(t)=(D_i/Tinf)/CL_i * (1-exp(-(CL_i/V_i)*Tinf))*exp(-(CL_i/V_i)*(t-t_dose-Tinf))',
    fixed_effects_log=fixed,parameters=object$parameters,
    random_effects='log(CL_i)=log(TVCL)+eta_CL_i; log(V_i)=log(TVV)+eta_V_i; eta_i~N(0,diag(omega_CL^2,omega_V^2))',
    omega=omega,variability=variability,
    error_model='log(Cobs_ij)=log(Cpred_ij)+epsilon_ij; epsilon~N(0,sigma^2), conditionally independent, homoscedastic on log scale',
    residual_sigma=fit$sigma,initial_parameters_per_kg=initial,controls=control,
    call=paste(deparse(fit$call),collapse='\n'),diagnostics=object$diagnostics),
  individual_comparison=list(method='minpack.lm::nlsLM; Levenberg-Marquardt nonlinear least squares on log concentration',
    structures=list('1cpt: CL,V','2cpt: CL,Vc,Q,Vp'),random_effects=FALSE,
    declared_starts_per_rat=list(one_compartment=2,two_compartment=4),max_iterations_per_start=300,
    within_rat_comparison='Same observations, log-Gaussian likelihood; AICc includes residual variance in k=3 or k=5',
    two_compartment_population_model_fitted=FALSE),
  independent_formula_check=list(max_absolute_prediction_difference=max(abs(manual-object$predicted)),status='PASSED'),
  inspection_environment=list(R=R.version.string,nlme=as.character(packageVersion('nlme')),minpack_lm=as.character(packageVersion('minpack.lm'))),
  limitations=list('Eight nonquantified records withheld without imputation; includes 2 BLQ',
    'No covariate selection, correlated CL/V random effects, residual autocorrelation or alternative residual model tested',
    'No population two-compartment model comparison or external validation',
    'Conditional predictions and individual empirical Bayes estimates reuse fitted data',
    'Typical CL/V are mass-normalized, not fitted animal-to-human allometric parameters'),
  human_review=list(decision='PENDING',approved_for_downstream_use=FALSE)),file.path(out,'rat_model_specification.json'))
cat('Saved model audit complete:',out,'\n');print(variability)
