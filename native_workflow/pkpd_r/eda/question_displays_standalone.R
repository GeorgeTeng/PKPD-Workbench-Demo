# All standalone requests share the globally enforced renderer.
script_path <- sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1])
source(file.path(dirname(normalizePath(script_path)),"question_displays.R"))
