# Dedicated EDA entry. Do not source the downstream fitting/integration loader.
args <- commandArgs(trailingOnly = TRUE)
if (!identical(args, "--check")) {
  stop("EDA_RUNTIME_NOT_IMPLEMENTED: only --check is available in this scaffold.",
       call. = FALSE)
}
script <- normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(),
                         value = TRUE)[1]), mustWork = TRUE)
root <- dirname(script)
lib <- Sys.getenv("PKPD_R_LIB",
                  unset = "C:/Users/georg/Documents/Codex/ScienceEnv/R-library")
if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("EDA_DEPENDENCY_MISSING: jsonlite; configure PKPD_R_LIB.", call. = FALSE)
}
source(file.path(root, "calculate.R"), local = TRUE, encoding = "UTF-8")
source(file.path(root, "visualize.R"), local = TRUE, encoding = "UTF-8")
stopifnot(is.function(eda_calculate), is.function(eda_visualize))
cat(jsonlite::toJSON(list(
  schema_version = "1.0", status = "SCAFFOLD_LOADED",
  runtime_implemented = FALSE, calculations_run = FALSE, figures_rendered = FALSE,
  r_version = R.version.string,
  agents = list(EC = "eda_calculate", EV = "eda_visualize"),
  dependencies = list(jsonlite = as.character(utils::packageVersion("jsonlite")),
    ggplot2 = if (requireNamespace("ggplot2", quietly = TRUE))
      as.character(utils::packageVersion("ggplot2")) else NULL)
), auto_unbox = TRUE, null = "null", pretty = TRUE), "\n")
