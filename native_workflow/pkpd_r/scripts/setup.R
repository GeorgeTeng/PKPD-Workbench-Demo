args <- commandArgs(trailingOnly = TRUE)
library_path <- if (length(args)) args[1] else Sys.getenv("PKPD_R_LIB", unset = "C:/Users/georg/Documents/Codex/ScienceEnv/R-library")
dir.create(library_path, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(library_path, .libPaths()))
needed <- c("jsonlite", "nlme", "minpack.lm")
missing <- needed[!vapply(needed, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) install.packages(missing, lib = library_path, repos = "https://cloud.r-project.org")
for (package in needed) cat(package, as.character(packageVersion(package)), "\n")

