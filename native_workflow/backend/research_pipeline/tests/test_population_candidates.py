import subprocess
from research_pipeline.common import PROJECT
from research_pipeline.engine import rscript_path


def test_vectorized_infusion_and_two_compartment_population_recovery(tmp_path):
    script=tmp_path/'population_check.R'
    script.write_text("""
source('pkpd_r/load.R')
source('pkpd_r/R/population_candidates.R')
times <- c(0,.005,1/60,.03,.08,.17,.33,.5,1,2,4,6,8,12)
dose <- data.frame(time_h=0,dose_mg=1,duration_h=1/60)
a <- iv_population_concentration(times,1,0,1/60,log(.2),log(.15),log(.08),log(.3))
b <- pk_2cpt(times,.2,.15,.08,.3,dose)
stopifnot(max(abs(a-b))<1e-12)
stopifnot(max(abs(iv_population_concentration(times,1,0,1/60,log(.2),log(.375))-pk_1cpt(times,.2,.375,dose)))<1e-12)
set.seed(925)
d <- do.call(rbind,lapply(1:18,function(i){
  t <- c(.03,.08,.17,.33,.5,1,2,4,6,8,12,18,24)
  c <- iv_population_concentration(t,1,0,1/60,log(.2)+rnorm(1,0,.2),log(.15)+rnorm(1,0,.15),log(.08),log(.3))
  data.frame(subject_id=paste0('R',i),time_h=t,concentration_mg_L=c*exp(rnorm(length(t),0,.04)),
    dose_mg_kg=1,dose_time_h=0,duration_h=1/60,species='rat')
}))
m <- list(drug='SyntheticTest',species='rat',matrix='plasma',concentration_unit='mg/L',time_unit='h',
  concentration_basis='total',record_level='individual',data_origin='synthetic',dose_unit='mg/kg',route='IV',regimen_type='single_dose')
truth <- c(CL=.2,Vc=.15,Q=.08,Vp=.3)
fit <- fit_population_candidate(d,m,2,truth,'diag_clv','lognormal')
stopifnot(inherits(fit$fit,'nlme'),fit$fit$method=='ML',length(fit$parameters$estimate)==4,
  max(abs(log(fit$parameters$estimate/unname(truth))))<.35)
stopifnot(abs(fit$diagnostics$log_likelihood_concentration-(as.numeric(logLik(fit$fit))-sum(log(d$concentration_mg_L))))<1e-8)
stopifnot(all(is.finite(predict_population_candidate(fit,d))))
stopifnot(identical(as.character(fit$data$subject_id),as.character(fit$fit$groups[[1]])))
# Two-component residual fitting uses fixed sigma and concentration-scale likelihood.
combined <- fit_population_candidate(d,m,2,truth,'diag_clv','combined')
stopifnot(combined$fit$sigma==1,combined$diagnostics$n_parameters==8,
  abs(combined$diagnostics$log_likelihood_concentration-as.numeric(logLik(combined$fit)))<1e-8,
  max(abs(log(combined$parameters$estimate/unname(truth))))<.35)
cat('Vectorized solver and population parameter recovery passed\\n')
""",encoding='utf-8')
    result=subprocess.run([rscript_path(),'--vanilla',str(script)],cwd=PROJECT,capture_output=True,text=True)
    assert result.returncode==0, result.stdout+'\n'+result.stderr
