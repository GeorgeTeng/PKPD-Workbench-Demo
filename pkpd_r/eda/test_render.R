# TEST-only EV: draw exact registered source values; no model, fitting, or inference.
args <- commandArgs(trailingOnly = TRUE)
lib <- Sys.getenv("PKPD_R_LIB", unset = "C:/Users/georg/Documents/Codex/ScienceEnv/R-library")
if (dir.exists(lib)) .libPaths(c(lib, .libPaths()))
if (!requireNamespace("jsonlite", quietly = TRUE)) stop("jsonlite unavailable", call. = FALSE)
if (length(args) != 2L) stop("Usage: test_render.R request.json output_directory", call. = FALSE)
request <- jsonlite::fromJSON(args[[1]], simplifyVector = FALSE)
stopifnot(identical(request$version, "EV_TEST_RENDER_1.0"))
directory <- normalizePath(args[[2]], mustWork = TRUE)
blue <- "#2166A5"; teal <- "#278774"; ink <- "#25364A"; grid_col <- "#E5EAF0"

cell <- function(row, column) {
  matches <- Filter(function(x) identical(x$column, column), row$cells)
  stopifnot(length(matches) == 1L)
  matches[[1]]$raw_value
}
num <- function(raw, nd = FALSE) {
  if (nd && identical(raw, "ND")) return(NULL)
  value <- suppressWarnings(as.numeric(raw))
  stopifnot(length(value) == 1L, is.finite(value))
  value
}
plot_data <- function(task) {
  roles <- task$column_roles
  kind <- task$display_spec$kind
  marks <- lapply(task$rows, function(row) {
    x <- cell(row, task$display_spec$x_variable_unit_scale$column)
    if (!identical(task$display_spec$x_variable_unit_scale$scale, "categorical")) x <- num(x)
    y <- num(cell(row, task$display_spec$y_variable_unit_scale$column), nd = identical(kind, "PD_REPORTED_MEAN_SD_BY_DOSE"))
    list(source_row = row$source_row, source_refs = row$row_source_ids, x = x, y = y,
         sd = if (identical(kind, "PD_REPORTED_MEAN_SD_BY_DOSE")) num(cell(row, roles$endpoint_sd), nd = TRUE) else NULL,
         n = if (identical(kind, "PD_REPORTED_MEAN_SD_BY_DOSE")) cell(row, roles$reported_n) else NULL,
         group = if (identical(kind, "PD_REPORTED_MEAN_SD_BY_DOSE")) cell(row, roles$strain) else NULL,
         status = if (is.null(y)) "ND_NOT_PLOTTED" else "PLOTTED")
  })
  baselines <- list()
  if (identical(kind, "PD_REPORTED_MEAN_SD_BY_DOSE")) {
    groups <- unique(vapply(task$rows, function(row) cell(row, roles$strain), character(1)))
    baselines <- lapply(groups, function(group) {
      rows <- Filter(function(row) identical(cell(row, roles$strain), group), task$rows)
      pairs <- vapply(rows, function(row) paste(cell(row, roles$baseline_mean), cell(row, roles$baseline_sd)), character(1))
      stopifnot(length(unique(pairs)) == 1L)
      source_refs <- unlist(lapply(rows, function(row) lapply(Filter(function(c) c$column %in% c(roles$baseline_mean, roles$baseline_sd), row$cells), function(c) c$source_id)), use.names = FALSE)
      list(group = group, y = num(cell(rows[[1]], roles$baseline_mean)),
           sd = num(cell(rows[[1]], roles$baseline_sd), nd = TRUE), n = NULL,
           n_status = "NOT_REPORTED", source_refs = unname(as.list(source_refs)))
    })
  }
  list(figure_id = task$figure_id, analysis_id = task$analysis_id,
       display_spec = task$display_spec, raw_rows = task$rows, source_context = task$source_context,
       marks = marks, baselines = baselines,
       interpretation = "Source values converted only to drawing coordinates; SD is source-reported. No new statistics.")
}
footer <- function(task) {
  notes <- unlist(task$signature$required_notes, use.names = FALSE)
  lines <- unlist(lapply(notes, function(line) strwrap(line, width = 135)), use.names = FALSE)
  for (i in seq_along(lines)) mtext(lines[[i]], side = 1, outer = TRUE, line = (i - 1) * 0.85 + 0.3, adj = 0.02, cex = 0.67, col = ink)
  mtext("TEST ONLY - full EP caption and exact source rows accompany this image", side = 3, outer = TRUE, line = 0.3, adj = 0.02, cex = 0.7, col = "#687789")
}
style <- function(task, panels = 1L) {
  notes <- unlist(lapply(unlist(task$signature$required_notes, use.names = FALSE), strwrap, width = 135), use.names = FALSE)
  par(mfrow = c(1, panels), oma = c((length(notes) - 1) * 0.85 + 2, 0.4, 2.1, 0.4),
      mar = c(4.9, 5.1, 3.1, 1.4), mgp = c(3.2, 0.9, 0), tcl = -0.25,
      family = "sans", col = ink, col.axis = ink, col.lab = ink, col.main = ink, las = 1,
      cex.main = 1.17, cex.lab = 1.02, cex.axis = 0.95, xaxs = "r", yaxs = "r")
}
errorbar <- function(x, y, sd, color = blue) {
  if (is.null(sd)) return(invisible(NULL))
  arrows(x, y - sd, x, y + sd, angle = 90, code = 3, length = 0.055, lwd = 1.8, col = color)
}
draw <- function(task, data) {
  kind <- task$display_spec$kind
  marks <- data$marks
  if (identical(kind, "PK_OBSERVED_MEAN_POINTS")) {
    style(task)
    x <- vapply(marks, function(d) d$x, numeric(1)); y <- vapply(marks, function(d) d$y, numeric(1))
    is_log <- identical(task$display_spec$y_variable_unit_scale$scale, "log10")
    stopifnot(!is_log || all(y > 0))
    plot(x, y, type = "n", log = if (is_log) "y" else "", bty = "l",
         xlab = "Time after single dose (h)", ylab = "Mean plasma concentration (mg/L)",
         main = "Observed group-mean PK")
    grid(col = grid_col, lty = 1); points(x, y, pch = 21, bg = blue, col = "white", cex = 1.6)
    if (is_log) mtext("Concentration axis: log10 scale; observed values unchanged", side = 3, line = 0.25, cex = 0.75)
  } else if (identical(kind, "PD_REPORTED_MEAN_SD_BY_DOSE")) {
    groups <- vapply(data$baselines, function(d) d$group, character(1))
    style(task, length(groups))
    limits <- unlist(lapply(c(marks, data$baselines), function(d) if (is.null(d$y)) NULL else c(d$y - if (is.null(d$sd)) 0 else d$sd, d$y + if (is.null(d$sd)) 0 else d$sd)))
    limits <- range(limits); span <- max(diff(limits), 1); ylim <- limits + c(-0.18, 0.26) * span
    for (group in groups) {
      selected <- Filter(function(d) identical(d$group, group), marks)
      baseline <- Filter(function(d) identical(d$group, group), data$baselines)[[1]]
      dose <- vapply(selected, function(d) d$x, numeric(1)); xlim <- range(dose); pad <- max(diff(xlim) * 0.09, 1)
      plot(NA, xlim = xlim + c(-pad, pad), ylim = ylim, type = "n", bty = "l", xaxt = "n",
           xlab = "Daily dose (mg/kg/24 h)", ylab = "Bacterial burden (log10 CFU/thigh)", main = group)
      axis(1, at = dose, labels = dose); grid(nx = NA, ny = NULL, col = grid_col, lty = 1)
      if (!is.null(baseline$sd)) rect(par("usr")[[1]], baseline$y - baseline$sd, par("usr")[[2]], baseline$y + baseline$sd,
                                    col = adjustcolor(teal, alpha.f = 0.11), border = NA)
      abline(h = baseline$y, col = teal, lwd = 1.6, lty = 2)
      for (d in selected) {
        if (is.null(d$y)) {
          text(d$x, ylim[[1]] + 0.07 * diff(ylim), paste0("ND\n(not plotted)\nn=", d$n), col = "#9A5634", cex = 0.68)
        } else {
          errorbar(d$x, d$y, d$sd)
          points(d$x, d$y, pch = 21, bg = blue, col = "white", cex = 1.35)
          text(d$x, d$y + if (is.null(d$sd)) 0 else d$sd + 0.05 * diff(ylim), paste0("n=", d$n), cex = 0.75, col = blue, pos = 3)
        }
      }
      legend("topright", legend = c("24 h mean +/- reported SD", "0 h baseline +/- SD; n not reported"),
             pch = c(16, NA), lty = c(NA, 2), col = c(blue, teal), bty = "n", cex = 0.65)
    }
  } else if (identical(kind, "MIC_STRAIN_POINTS")) {
    style(task)
    strains <- vapply(marks, function(d) d$x, character(1)); y <- vapply(marks, function(d) d$y, numeric(1))
    x <- seq_along(strains)
    plot(x, y, type = "n", xaxt = "n", bty = "l", xlim = c(0.5, length(x) + 0.5), ylim = c(0, max(y) * 1.4),
         xlab = "K. pneumoniae strain", ylab = "Reported PMB MIC (mg/L)", main = "Source-reported strain MICs")
    axis(1, at = x, labels = strains, tick = FALSE); grid(nx = NA, ny = NULL, col = grid_col, lty = 1)
    points(x, y, pch = 21, bg = blue, col = "white", cex = 1.7)
    text(x, y, labels = format(y, trim = TRUE), pos = 3, cex = 0.92, col = blue)
  } else stop("Unsupported typed display; no fallback", call. = FALSE)
  footer(task)
}
figures <- lapply(request$tasks, function(task) {
  stopifnot(grepl("^F[0-9]{3}$", task$figure_id))
  data <- plot_data(task)
  fid <- task$figure_id
  height <- if (identical(task$display_spec$kind, "PD_REPORTED_MEAN_SD_BY_DOSE")) 1250L else 1100L
  png(file.path(directory, paste0(fid, ".png")), width = 1700L, height = height, res = 170L, bg = "white", pointsize = 12)
  tryCatch(draw(task, data), finally = dev.off())
  svg(file.path(directory, paste0(fid, ".svg")), width = 10, height = height / 170, pointsize = 12, bg = "white")
  tryCatch(draw(task, data), finally = dev.off())
  jsonlite::write_json(data, file.path(directory, paste0(fid, ".plotted_rows.json")), auto_unbox = TRUE, pretty = TRUE,
                       na = "null", null = "null", digits = NA)
  list(figure_id = fid, analysis_id = task$analysis_id, kind = task$display_spec$kind, rendered = TRUE)
})
jsonlite::write_json(list(version = "EV_TEST_RENDERED_1.0", figures = figures), file.path(directory, "rendered.json"),
                     auto_unbox = TRUE, pretty = TRUE, na = "null", null = "null")
