# EDA Distribution figures (r1.2, figures DIS-1a to DIS-6b): draw the plot specs written by research_pipeline/eda_distribution.py.
# Usage: Rscript --vanilla distribution_figures.R <plot_specs.json> <out_dir>
# Same drawing code as absorption_figures.R plus one layer kind, "path" (points joined in time order, used by the DIS-4e phase plot).
# Python computes every plotted value; this script only draws. Requires ggplot2 and jsonlite.
if (nzchar(Sys.getenv("PKPD_R_LIB"))) .libPaths(c(Sys.getenv("PKPD_R_LIB"), .libPaths()))
suppressPackageStartupMessages({
  library(jsonlite)
  library(ggplot2)
  library(grid)
})

args <- commandArgs(trailingOnly = TRUE)
specs <- fromJSON(args[1], simplifyVector = FALSE)
out_dir <- args[2]

INK <- "#17364b"; INK2 <- "#4b6273"; MUTED <- "#8a9aa6"; GRID <- "#e4eaf0"
# use the shared EDA style (pkpd_r/eda/plot_style.R) when it sits next to this script
self <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])
style <- file.path(dirname(normalizePath(self)), "plot_style.R")
HAS_STYLE <- file.exists(style) && requireNamespace("cowplot", quietly = TRUE)
if (HAS_STYLE) source(style)
new_gg <- packageVersion("ggplot2") >= "3.4.0"
inside_arg <- packageVersion("ggplot2") >= "3.5.0"
LW <- if (new_gg) "linewidth" else "size"

num <- function(v) if (length(v) == 0) numeric(0) else vapply(v, function(z) if (is.null(z)) NA_real_ else as.numeric(z), 0)
nz <- function(x, d) if (is.null(x)) d else x
shape_of <- function(s) switch(nz(s, "circle"), circle = 16, open = 1, ring = 1, diamond_open = 23, cross = 4, dash = 95, square = 15, 16)
lty_of <- function(s) switch(nz(s, "solid"), dashed = "22", dotted = "12", "solid")
lab_fmt <- function(x) format(x, trim = TRUE, drop0trailing = TRUE, scientific = FALSE)
with_lw <- function(lst, w) { lst[[LW]] <- w; lst }

TXT <- 1.25  # annotation text scale; figures are viewed two to a row in the gallery

theme_abs <- function() {
  if (HAS_STYLE) {
    return(pkpd_theme() + theme(
      plot.title = element_text(face = "bold", size = 13, colour = INK, hjust = 0, margin = margin(b = 6)),
      axis.title = element_text(size = 12, colour = INK2), axis.text = element_text(size = 11, colour = "#334b5e"),
      legend.text = element_text(size = 10.5, colour = INK2), legend.key.height = unit(13, "pt"),
      legend.background = element_rect(fill = scales::alpha("white", 0.85), colour = NA),
      plot.margin = margin(10, 14, 8, 10)))
  }
  theme_minimal(base_size = 12) +
    theme(panel.grid.minor = element_blank(),
          panel.grid.major = element_line(colour = GRID, linewidth = 0.35),
          axis.line = element_line(colour = MUTED, linewidth = 0.35),
          axis.ticks = element_line(colour = MUTED, linewidth = 0.3),
          axis.text = element_text(colour = INK2, size = 11),
          axis.title = element_text(colour = INK2, size = 11.5),
          plot.title = element_text(colour = INK, size = 12.5, face = "bold", hjust = 0, margin = margin(b = 6)),
          plot.title.position = "plot",
          legend.title = element_blank(), legend.text = element_text(size = 10, colour = INK2),
          legend.background = element_rect(fill = scales::alpha("white", 0.85), colour = NA),
          legend.key.height = unit(13, "pt"), legend.key.width = unit(18, "pt"),
          legend.margin = margin(2, 4, 2, 4),
          plot.margin = margin(8, 12, 6, 8),
          plot.background = element_rect(fill = "white", colour = NA),
          panel.background = element_rect(fill = "white", colour = NA))
}

legend_pos <- function(p) switch(p, top_right = c(0.99, 0.99), top_left = c(0.01, 0.99), bottom_left = c(0.01, 0.01),
                                 bottom_right = c(0.99, 0.01), top = c(0.5, 0.99), c(0.99, 0.99))

# Draw notes in the panel viewport. Passing its edges through a log scale
# transforms annotation_custom's default -Inf bounds and misplaces the text.
GeomPanelNote <- ggproto("GeomPanelNote", Geom,
  draw_panel = function(data, panel_params, coord, note) note
)

build_panel <- function(pn) {
  g <- ggplot()
  keys <- character(0); kcol <- character(0); kshape <- c(); klty <- c(); klw <- c(); ksize <- c(); kfill <- c()
  addkey <- function(lab, col, shape = NA, lty = "blank", lw = 0, size = 2.4, fill = NA) {
    keys <<- c(keys, lab); kcol <<- c(kcol, col); kshape <<- c(kshape, shape); klty <<- c(klty, lty)
    klw <<- c(klw, lw); ksize <<- c(ksize, size); kfill <<- c(kfill, fill)
  }
  for (L in pn$layers) {
    col <- nz(L$color, INK); lab <- L$label
    k <- L$kind
    if (k == "band") {
      ylo <- if (isTRUE(pn$ylog)) 0 else -Inf  # on a log axis 0 maps to the lower edge (-Inf would become NaN)
      g <- g + annotate("rect", xmin = L$xmin, xmax = L$xmax, ymin = ylo, ymax = Inf, fill = col, alpha = L$alpha)
    } else if (k == "area") {
      d <- data.frame(x = num(L$x), y = num(L$y))
      g <- g + geom_ribbon(data = d, aes(x = x, ymin = 0, ymax = y), fill = col, alpha = L$alpha)
    } else if (k == "points") {
      d <- data.frame(x = num(L$x), y = num(L$y))
      sh <- shape_of(L$shape)
      sz <- nz(L$size, 2.6) * (if (identical(L$shape, "dash")) 1.8 else 1)
      st <- nz(L$stroke, 1) * 0.9
      if (nrow(d) == 0) d <- data.frame(x = NA_real_, y = NA_real_)
      if (!is.null(lab)) {
        d$key <- lab
        g <- g + geom_point(data = d, aes(x = x, y = y, colour = key), shape = sh, size = sz, stroke = st, fill = "white", na.rm = TRUE)
        addkey(lab, col, shape = sh, size = min(sz, 3.2), fill = "white")
      } else {
        g <- g + geom_point(data = d, aes(x = x, y = y), colour = col, shape = sh, size = sz, stroke = st, fill = "white", na.rm = TRUE)
      }
    } else if (k == "line") {
      d <- data.frame(x = num(L$x), y = num(L$y))
      a <- with_lw(list(data = d, linetype = lty_of(L$lty), alpha = nz(L$alpha, 1)), L$lw)
      if (!is.null(lab)) {
        d$key <- lab; a$data <- d; a$mapping <- aes(x = x, y = y, colour = key)
        addkey(lab, col, lty = lty_of(L$lty), lw = L$lw)
      } else { a$mapping <- aes(x = x, y = y); a$colour <- col }
      g <- g + do.call(geom_line, a)
    } else if (k == "path") {
      # time-ordered path (geom_path keeps the data order; geom_line would sort by x)
      d <- data.frame(x = num(L$x), y = num(L$y))
      a <- with_lw(list(data = d, mapping = aes(x = x, y = y), colour = col, linetype = lty_of(L$lty), alpha = nz(L$alpha, 1),
                        arrow = grid::arrow(length = unit(0.08, "in"), type = "closed")), L$lw)
      g <- g + do.call(geom_path, a)
    } else if (k == "segment") {
      d <- data.frame(x = num(L$x), y = num(L$y), xend = num(L$xend), yend = num(L$yend))
      a <- with_lw(list(data = d, linetype = lty_of(L$lty), lineend = "butt"), L$lw)
      if (!is.null(lab)) {
        d$key <- lab; a$data <- d; a$mapping <- aes(x = x, y = y, xend = xend, yend = yend, colour = key)
        addkey(lab, col, lty = "solid", lw = L$lw)
      } else { a$mapping <- aes(x = x, y = y, xend = xend, yend = yend); a$colour <- col }
      g <- g + do.call(geom_segment, a)
    } else if (k == "hline") {
      d <- data.frame(y = L$y)
      a <- with_lw(list(data = d, linetype = lty_of(L$lty)), L$lw)
      if (!is.null(lab)) {
        d$key <- lab; a$data <- d; a$mapping <- aes(yintercept = y, colour = key)
        addkey(lab, col, lty = lty_of(L$lty), lw = L$lw)
      } else { a$mapping <- aes(yintercept = y); a$colour <- col }
      g <- g + do.call(geom_hline, a)
    } else if (k == "vline") {
      g <- g + do.call(geom_vline, with_lw(list(xintercept = L$x, colour = col, linetype = lty_of(L$lty)), L$lw))
    } else if (k == "bars") {
      g <- g + geom_col(data = data.frame(x = num(L$x), y = num(L$y)), aes(x = x, y = y), fill = col, width = 0.65)
    } else if (k == "text") {
      if (isTRUE(L$npc)) {
        note <- textGrob(L$label, x = unit(L$x, "npc"), y = unit(L$y, "npc"),
                         hjust = L$hjust, vjust = L$vjust,
                         gp = gpar(col = nz(L$color, INK2), fontsize = L$size * 2.85 * TXT, lineheight = 1.05))
        g <- g + layer(geom = GeomPanelNote, stat = "identity", position = "identity",
                       data = data.frame(row = 1L), mapping = NULL, inherit.aes = FALSE,
                       show.legend = FALSE, params = list(note = note))
      } else {
        g <- g + annotate("text", x = L$x, y = L$y, label = L$label, hjust = L$hjust, vjust = L$vjust, size = L$size * TXT,
                          colour = nz(L$color, INK2), lineheight = 1.0)
      }
    }
  }
  if (length(keys)) {
    keep <- !duplicated(keys)
    ov <- list(shape = kshape[keep], linetype = klty[keep], size = ksize[keep], fill = kfill[keep])
    ov[[LW]] <- klw[keep]
    g <- g + scale_colour_manual(values = setNames(kcol[keep], keys[keep]), breaks = keys[keep], limits = keys[keep], drop = FALSE) +
      guides(colour = guide_legend(override.aes = ov))
  }
  xb <- if (is.null(pn$xbreaks)) waiver() else num(pn$xbreaks)
  xl <- if (is.null(pn$xlabels)) (if (is.null(pn$xbreaks)) waiver() else lab_fmt(num(pn$xbreaks))) else unlist(pn$xlabels)
  if (isTRUE(pn$xlog2)) {
    g <- g + scale_x_continuous(trans = "log2", breaks = xb, labels = xl)
  } else if (isTRUE(pn$xlog)) {
    has_path <- any(vapply(pn$layers, function(layer) identical(layer$kind, "path"), logical(1)))
    x_expand <- if (has_path) expansion(mult = c(0.05, 0.16)) else waiver()
    g <- g + scale_x_log10(labels = lab_fmt, expand = x_expand)
  } else {
    g <- g + scale_x_continuous(breaks = xb, labels = xl)
  }
  if (isTRUE(pn$ylog)) g <- g + scale_y_log10(labels = lab_fmt)
  xlim <- if (is.null(pn$xlim)) NULL else num(pn$xlim)
  ylim <- if (is.null(pn$ylim)) NULL else num(pn$ylim)
  g <- g + coord_cartesian(xlim = xlim, ylim = ylim, clip = "off")
  g <- g + labs(title = nz(pn$title, ""), x = nz(pn$xlab, ""), y = nz(pn$ylab, "")) + theme_abs()
  pos <- nz(pn$legend, "none")
  if (pos == "none" || !length(keys)) {
    g <- g + theme(legend.position = "none")
  } else {
    xy <- legend_pos(pos)
    if (inside_arg) g <- g + theme(legend.position = "inside", legend.position.inside = xy, legend.justification = xy)
    else g <- g + theme(legend.position = xy, legend.justification = xy)
  }
  if (isTRUE(pn$blank)) {
    g <- g + theme(axis.line = element_blank(), axis.text = element_blank(), axis.ticks = element_blank(),
                   panel.grid.major = element_blank(), axis.title = element_blank()) + coord_cartesian(xlim = c(0, 1), ylim = c(0, 1))
  }
  if (identical(pn$yticks, FALSE)) g <- g + theme(axis.text.y = element_blank(), axis.ticks.y = element_blank(), panel.grid.major.y = element_blank())
  g
}

open_device <- function(path, w, h, dpi) {
  if (HAS_STYLE && requireNamespace("ragg", quietly = TRUE)) return(pkpd_png(path, w, h))
  if (requireNamespace("ragg", quietly = TRUE)) ragg::agg_png(path, width = w, height = h, units = "in", res = dpi, background = "white")
  else png(path, width = w, height = h, units = "in", res = dpi, bg = "white", type = if (capabilities("cairo")) "cairo" else getOption("bitmapType"))
}

for (f in specs$figures) {
  path <- file.path(out_dir, f$file)
  open_device(path, f$width, f$height, f$dpi)
  grid.newpage()
  has_title <- nzchar(nz(f$title, ""))
  th <- if (has_title) unit(0.42, "in") else unit(0, "in")
  np <- length(f$panels)
  ncol <- as.integer(nz(f$ncol, np)); nrow <- ceiling(np / ncol)  # small multiples wrap into rows
  wd <- num(f$widths); if (length(wd) != ncol) wd <- rep(1, ncol)
  pushViewport(viewport(layout = grid.layout(1 + nrow, ncol, heights = unit.c(th, unit(rep(1, nrow), "null")),
                                             widths = unit(wd, "null"))))
  if (has_title) {
    pushViewport(viewport(layout.pos.row = 1, layout.pos.col = 1:ncol))
    grid.text(f$title, x = unit(0.012, "npc"), hjust = 0, gp = gpar(fontsize = 14, col = INK, fontface = "bold"))
    popViewport()
  }
  for (i in seq_along(f$panels)) {
    print(build_panel(f$panels[[i]]), vp = viewport(layout.pos.row = 2 + (i - 1) %/% ncol, layout.pos.col = 1 + (i - 1) %% ncol))
  }
  invisible(dev.off())
}
cat(sprintf("rendered %d figures with ggplot2 %s\n", length(specs$figures), as.character(packageVersion("ggplot2"))))
