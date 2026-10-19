import subprocess

from research_pipeline.common import PROJECT
from research_pipeline.engine import rscript_path


def test_sparse_hill_is_explicit_and_cannot_produce_aicc(tmp_path):
    script=tmp_path/'check_sparse_hill.R'
    script.write_text("""
source('pkpd_r/load.R')
x <- c(0,.2,.8,2,5,12)
d <- data.frame(unit_id=1:6,index=x,response=emax_response(x,6,4,1,1.6)+c(.02,-.03,.01,.02,-.02,.01))
default <- tryCatch(fit_index_emax(d,'index',estimate_hill=TRUE),error=identity)
stopifnot(inherits(default,'error'),grepl('Insufficient exposure support',conditionMessage(default)))
fit <- fit_index_emax(d,'index',estimate_hill=TRUE,sparse_exploratory=TRUE)
stopifnot(fit$sparse_exploratory,stats::df.residual(fit$fit)==2,
  fit$diagnostics$n_parameters==5,is.na(fit$diagnostics$AICc),
  any(grepl('Sparse exploratory',fit$warnings)))
# Independent Gaussian ML formula includes the estimated error variance.
sse <- sum((d$response-fit$predicted)^2)
aic <- 6*(log(2*pi)+1+log(sse/6))+2*5
stopifnot(abs(fit$diagnostics$AIC-aic)<1e-8)
too_small <- tryCatch(fit_index_emax(d[1:5,],'index',estimate_hill=TRUE,sparse_exploratory=TRUE),error=identity)
stopifnot(inherits(too_small,'error'))
ordinary <- fit_index_emax(d,'index')
stopifnot(!ordinary$sparse_exploratory,is.finite(ordinary$diagnostics$AICc))
cat('Sparse review guard and information criteria verified\\n')
""",encoding='utf-8')
    result=subprocess.run([rscript_path(),'--vanilla',str(script)],cwd=PROJECT,capture_output=True,text=True)
    assert result.returncode==0, result.stdout+'\n'+result.stderr
