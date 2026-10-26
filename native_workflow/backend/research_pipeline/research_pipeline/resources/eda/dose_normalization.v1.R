args <- commandArgs(trailingOnly=TRUE)
lib <- Sys.getenv('PKPD_R_LIB', '')
if(nzchar(lib)) .libPaths(c(lib,.libPaths()))
suppressPackageStartupMessages(library(ggplot2))
library(jsonlite)
plan <- fromJSON(args[1],simplifyVector=FALSE); out <- args[2]
source(args[3])
artifacts <- list()
for(s in plan$plots) {
  rows <- lapply(s$rows,function(r) {
    stopifnot(is.numeric(r$dose),is.finite(r$dose),r$dose>=0)
    r$y <- if(r$dose>0 && identical(r$status,'QUANTIFIED') && is.numeric(r$raw_y) && is.finite(r$raw_y)) r$raw_y/r$dose else NA_real_
    r
  })
  good <- Filter(function(r) isTRUE(r$plot_eligible),rows)
  d <- do.call(rbind,lapply(good,function(r) data.frame(x=r$x,y=r$y,group=r$group)))
  groups <- unique(vapply(rows,function(r) r$group,character(1)))
  d$group <- factor(d$group,levels=groups)
  p <- ggplot(d,aes(x=x,y=y,color=group))+geom_point(size=2.5)+
    labs(title=paste(s$figure_index,'|',s$title),subtitle=s$subtitle,
         x=s$x_label,y=s$y_label,color='Single dose',
         caption=paste(strwrap(s$caption,width=125),collapse='\n'))+
    theme_minimal(base_size=12)+theme(legend.position='bottom',
      plot.title=element_text(face='bold',color='#19384b'),
      plot.caption=element_text(hjust=0,size=9,color='#536979'),panel.grid.minor=element_blank())
  # Guide lines only when every row is quantifiable and times are unique per source group.
  line_ok <- length(good)==length(rows) && !anyDuplicated(paste(d$group,d$x))
  if(line_ok) p <- p+geom_line(linewidth=.55)
  if(identical(s$y_scale,'log10')) p <- p+scale_y_log10()
  p <- p+scale_colour_manual(values=pkpd_colours(length(groups)))+scale_x_continuous()
  p <- pkpd_axis_detail(p,d,s$axis_detail)$plot
  p <- pkpd_time_axis_labels(p,s$axis_detail,width_inches=12)$plot
  if(length(good)!=length(rows)) p <- p+labs(caption=paste(p$labels$caption,
    'Nonquantified or log-ineligible records retained in the companion table; no substitute values or guide lines.',sep='\n'))
  pngname <- paste0(s$id,'.png'); pdfname <- paste0(s$id,'.pdf'); dataname <- paste0(s$id,'.plotted_rows.json')
  ggsave(file.path(out,pngname),p,width=12,height=7.4,dpi=160,bg='white')
  ggsave(file.path(out,pdfname),p,width=12,height=7.4,device=cairo_pdf,bg='white')
  write_json(rows,file.path(out,dataname),auto_unbox=TRUE,pretty=TRUE,digits=16,null='null',na='null')
  flat <- fromJSON(file.path(out,dataname));write.csv(flat,file.path(out,paste0(s$id,'.plotted_rows.csv')),row.names=FALSE,na='')
  facts <- list(x_label=s$x_label,y_label=s$y_label,figure_index=s$figure_index,
    panels=1L,point_count=nrow(d),error_bar_count=0L,
    elements=if(line_ok) c('points','lines') else c('points'),
    calculated_quantity='C(t)/Dose',raw_values_preserved=TRUE)
  auditname <- paste0(s$id,'.audit.json')
  write_json(list(rendered_scales=list(x='linear',y=s$y_scale),formula='raw_y / dose',
    denominator_basis=s$dose_contract$dose_basis,source_records_modified=FALSE,
    interpolation=FALSE,model_fit=FALSE,scientific_release=FALSE),file.path(out,auditname),auto_unbox=TRUE,pretty=TRUE)
  artifacts[[length(artifacts)+1]] <- list(id=s$id,kind='dose_normalized_profile',
    png=pngname,pdf=pdfname,data=dataname,audit=auditname,panels=1L,render_facts=facts,
    dataset_ids=unique(vapply(rows,function(r) r$dataset_id,character(1))))
}
write_json(list(artifacts=artifacts),file.path(out,'dose_normalization_manifest.json'),auto_unbox=TRUE,pretty=TRUE)
