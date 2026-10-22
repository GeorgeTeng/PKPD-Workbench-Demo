# Source this file once. All functions use explicit units and declared data roles.
.pkpd_sources <- Filter(function(x) !is.null(x), lapply(sys.frames(), function(frame) frame$ofile))
.pkpd_file <- if(length(.pkpd_sources)) tail(.pkpd_sources, 1L)[[1L]] else NULL
if (is.null(.pkpd_file)) stop("Use source('path/to/pkpd_r/load.R').")
.pkpd_root <- dirname(normalizePath(.pkpd_file, mustWork = TRUE))
.pkpd_lib <- Sys.getenv("PKPD_R_LIB", unset = "C:/Users/georg/Documents/Codex/ScienceEnv/R-library")
if (dir.exists(.pkpd_lib)) .libPaths(c(.pkpd_lib, .libPaths()))
for (.pkpd_package in c("jsonlite", "nlme", "minpack.lm")) {
  if (!requireNamespace(.pkpd_package, quietly = TRUE))
    stop("Missing package: ", .pkpd_package, ". Run scripts/setup.R first.")
}
for (.pkpd_module in c("validation.R", "indices.R", "pk_models.R", "normalized_pk.R", "endpoint.R", "longitudinal_response.R", "export.R")) {
  source(file.path(.pkpd_root, "R", .pkpd_module), local = FALSE, encoding = "UTF-8")
}
PKPD_VERSION <- "0.1.1"
rm(.pkpd_file, .pkpd_sources, .pkpd_lib, .pkpd_module, .pkpd_package)
