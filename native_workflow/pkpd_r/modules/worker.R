args <- commandArgs(trailingOnly=TRUE)
if(length(args)!=2L) stop("Usage: Rscript worker.R module_input.json module_result.json")
script <- normalizePath(sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1]),mustWork=TRUE)
root <- dirname(dirname(script))
source(file.path(root,"load.R"),encoding="UTF-8")
source(file.path(root,"modules/shared.R"),encoding="UTF-8")
source(file.path(root,"modules/pk_longitudinal.R"),encoding="UTF-8")
source(file.path(root,"modules/pkpd_index.R"),encoding="UTF-8")
out <- args[2]
request <- jsonlite::read_json(args[1],simplifyVector=FALSE)
status <- tryCatch({
  if(!identical(request$schema_version,"1.0")) stop("Unsupported module input schema.")
  dir.create(dirname(out),recursive=TRUE,showWarnings=FALSE)
  result <- switch(request$module,
    pk_longitudinal=run_pk_longitudinal(request,dirname(out)),
    pkpd_index=run_pkpd_index(request,dirname(out)),
    stop("Unknown module."))
  result$human_review <- list(status="PENDING",reviewer="",decision="PENDING",
    approved_for_downstream_use=FALSE,scope="model_results",
    note="Successful numerical execution is not human acceptance of the model or its predictions.")
  write_pkpd_json(list(status="SUCCEEDED",result=result),out)
  0L
},error=function(e) {
  write_pkpd_json(list(status="FAILED",result=NULL,error=list(code="R_ANALYSIS_ERROR",message=conditionMessage(e))),out)
  1L
})
quit(status=status)
