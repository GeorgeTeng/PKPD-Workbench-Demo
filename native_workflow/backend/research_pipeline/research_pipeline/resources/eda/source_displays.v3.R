# Deterministic rendering of audited source-native projections. No model or EC call.
args <- commandArgs(trailingOnly=TRUE)
.libPaths(c("C:/Users/georg/Documents/Codex/ScienceEnv/R-library",.libPaths()))
suppressPackageStartupMessages(library(ggplot2))
library(jsonlite)
plan <- fromJSON(args[1],simplifyVector=FALSE)
out <- args[2]; dir.create(out,recursive=TRUE,showWarnings=FALSE)
`%or%` <- function(x,y) if(is.null(x)) y else x
script_path <- sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1])
source(args[3])
theme_source <- pkpd_theme()
artifacts <- list()
for (s in plan$plots) {
  stopifnot(isTRUE(s$standalone),is.character(s$figure_index),nzchar(s$figure_index),
            is.character(s$x_label),nzchar(s$x_label),is.character(s$y_label),nzchar(s$y_label))
  rows <- lapply(s$rows,function(r) data.frame(
    dataset_id=r$dataset_id,record_id=r$record_id,y_column=r$y_column,
    x=r$x,y=r$y %or% NA_real_,error=r$error %or% NA_real_,n=r$n %or% NA_real_,
    panel=r$panel,group=r$group,category=r$category_label,bound=r$bound,
    role=r$display_role,status_label=r$status_label,zero_qualification=r$zero_qualification,
    eligible=r$plot_eligible %or% TRUE,exclusion=r$display_exclusion_reason %or% "",
    status=r$original_status,raw_y=as.character(r$raw_y %or% "NULL"),
    stringsAsFactors=FALSE))
  d <- do.call(rbind,rows)
  d$panel <- factor(d$panel,levels=unique(d$panel))
  d$group[nchar(d$group)==0]<-"Source observations"
  d$group <- factor(d$group,levels=unique(d$group))
  stopifnot(nlevels(d$panel)==1L)
  valid <- d[!is.na(d$y) & d$eligible,]
  stopifnot(nrow(valid)>0)
  if(s$categorical) {
    # Source-specific labels include dataset IDs, so identical strain names do not join studies.
    d$category <- factor(d$category,levels=unique(d$category))
    valid <- d[!is.na(d$y) & d$eligible,]
    p <- ggplot(valid,aes(x=category,y=y,colour=group))
  } else p <- ggplot(valid,aes(x=x,y=y,colour=group))
  # Preserve original intervals in JSON; do not silently clip them at the log boundary.
  interval_ok <- !is.na(valid$error)
  nonpositive_intervals <- 0L
  if(s$scale=="log10") {
    nonpositive_intervals <- sum(interval_ok & (valid$y-valid$error<=0),na.rm=TRUE)
    interval_ok <- interval_ok & (valid$y-valid$error>0)
    if(nonpositive_intervals>0L) s$caption<-paste(s$caption,
      paste0(nonpositive_intervals," SD/uncertainty intervals reach nonpositive values; their bars are omitted on this log axis. Full intervals remain in the linear view and companion rows."))
  }
  if(any(interval_ok,na.rm=TRUE)) {
    stopifnot(all(valid$error[!is.na(valid$error)]>=0))
    p <- p+geom_errorbar(data=valid[which(interval_ok),],aes(ymin=y-error,ymax=y+error),width=0,linewidth=.55,na.rm=TRUE)
  }
  if(any(nzchar(valid$bound))) {
    p <- p+geom_point(aes(shape=ifelse(bound=="","Reported value",ifelse(bound=="<","Upper bound (<)","Lower bound (>)"))),size=2.7)+
      scale_shape_manual(values=c("Reported value"=16,"Upper bound (<)"=25,"Lower bound (>)"=24))
    p <- p+geom_text(data=valid[nzchar(valid$bound),],aes(label=raw_y),hjust=-.15,vjust=-.6,size=2.8,show.legend=FALSE)
  } else p <- p+geom_point(aes(shape=role),size=2.5,alpha=.9)+
    scale_shape_manual(values=c(SOURCE_OBSERVATION=16,SOURCE_SUMMARY=18),
      labels=c(SOURCE_OBSERVATION="Source observation",SOURCE_SUMMARY="Source summary"))
  if(any(!is.na(valid$n))) p<-p+geom_text(aes(y=y+error,label=paste0("n=",n)),vjust=-.7,size=3,show.legend=FALSE)
  # Categorical panels keep separate labels while honoring requested y scales.
  facet_scales <- s$facet_scales
  stopifnot(facet_scales %in% c("fixed","free_x","free_y","free"))
  if(s$categorical) facet_scales <- if(facet_scales %in% c("free_y","free")) "free" else "free_x"
  p<-p+
    labs(title=paste(strwrap(paste(s$figure_index,s$title,sep=" | "),width=95),collapse="
"),subtitle=s$question,x=s$x_label,y=s$y_label,colour="Series / group",shape="Status",
     caption=paste(strwrap(s$caption,width=125),collapse="\n"))+theme_source+theme(legend.title=element_text(size=10))
  if(s$scale=="log10") {
    stopifnot(all(valid$y>0));p<-p+scale_y_log10(expand=expansion(mult=c(.12,.22)))
  } else p<-p+scale_y_continuous(expand=expansion(mult=c(.1,.2)))
  if(s$categorical) p<-p+scale_x_discrete(drop=FALSE)+
    theme(axis.text.x=element_text(angle=35,hjust=1,size=9))
  p<-p+scale_colour_manual(values=pkpd_colours(nlevels(d$group)))
  
  if(!s$categorical) p<-p+scale_x_continuous(breaks=if(length(unique(d$x))<=12) sort(unique(d$x)) else waiver())
  p<-p+theme(legend.position="bottom")
  axis_detail<-pkpd_axis_detail(p,d,s$axis_detail %or% s$first_observation)
  p<-axis_detail$plot
  zero_notes<-unique(d$zero_qualification[nzchar(d$zero_qualification)])
  if(length(zero_notes)) p<-p+labs(caption=paste(p$labels$caption,paste(zero_notes,collapse="; "),sep="\n"))
  missing<-d[is.na(d$y) | !d$eligible,];strip<-NULL
  if(nrow(missing)) {
    missing$source_slot<-as.character(missing$group)
    mapping<-if(s$categorical) aes(x=category,y=source_slot) else aes(x=x,y=source_slot)
    strip<-ggplot(missing,mapping)+geom_text(aes(label=status_label),size=3,colour="#943d37")+
      labs(x=s$x_label,y=NULL,title="Source statuses / summaries (no response coordinate)")+
      theme_source+theme(plot.title=element_text(size=11),axis.text.y=element_text(size=8))
    if(s$categorical) strip<-strip+scale_x_discrete(limits=levels(d$category),drop=FALSE)+
      theme(axis.text.x=element_text(angle=35,hjust=1,size=9))
    else strip<-strip+scale_x_continuous(limits=range(d$x),breaks=sort(unique(d$x)))

  }
  h<-max(6,2.8*ceiling(nlevels(d$panel)/s$ncol)+2.3)
  sh<-if(is.null(strip)) 0 else max(1.8,.23*length(unique(missing$source_slot))+1.4)
  context<-NULL
  if(length(s$context_rows)) {
    labels<-names(s$context_rows[[1]]$values)
    cells<-do.call(rbind,lapply(seq_along(s$context_rows),function(i) {
      z<-s$context_rows[[i]]
      data.frame(x=seq_along(labels),y=-i,
        label=vapply(z$values,function(v) paste(strwrap(as.character(v),width=if(nchar(as.character(v))>40) 43 else 34),collapse="\n"),character(1)))
    }))
    context<-ggplot(cells,aes(x=x,y=y,label=label))+geom_text(hjust=0,size=3.1)+
      scale_x_continuous(breaks=seq_along(labels),labels=labels,limits=c(.9,4.1),position="top")+
      scale_y_continuous(breaks=NULL,expand=expansion(add=.65))+
      labs(title="Separate source block: literal MIC context (not pooled)",x=NULL,y=NULL)+theme_source+
      theme(panel.grid=element_blank(),axis.text.x=element_text(hjust=0),plot.title=element_text(size=11))
  }
  ch<-if(is.null(context)) 0 else 3.8
  draw<-function() {
    plots<-list(p);heights<-c(h)
    if(!is.null(strip)) {plots<-c(plots,list(strip));heights<-c(heights,sh)}
    if(!is.null(context)) {plots<-c(plots,list(context));heights<-c(heights,ch)}
    print(patchwork::wrap_plots(plots,ncol=1,heights=heights))
  }
  pkpd_png(file.path(out,paste0(s$id,".png")),width=12,height=h+sh+ch);draw();dev.off()
  pkpd_pdf(file.path(out,paste0(s$id,".pdf")),width=12,height=h+sh+ch);draw();dev.off()
  # Exact records, including raw compound text, status and bound semantics.
  write_json(s$context_rows,file.path(out,paste0(s$id,".context_rows.json")),pretty=TRUE,auto_unbox=TRUE,digits=17,null="null")
  write_json(s$rows,file.path(out,paste0(s$id,".plotted_rows.json")),pretty=TRUE,auto_unbox=TRUE,digits=17,null="null")
  built<-ggplot_build(p)
  geoms<-vapply(p$layers,function(z) class(z$geom)[1],character(1))
  count_geom<-function(name) sum(vapply(which(geoms==name),function(i) nrow(built$data[[i]]),integer(1)))
  elements<-c(if(count_geom("GeomPoint")>0) "POINTS",if(count_geom("GeomErrorbar")>0) "ERROR_BARS",
              if(nrow(missing)>0) "STATUS_TEXT",if(length(s$context_rows)>0) "CONTEXT_TABLE")
  surface<-list(elements=as.list(elements),point_count=count_geom("GeomPoint"),line_segments=0,
    error_bar_count=count_geom("GeomErrorbar"),figure_index=s$figure_index,x_label=p$labels$x,y_label=p$labels$y,
    panels=length(built$layout$panel_params),category_labels=if(s$categorical) as.list(built$layout$panel_params[[1]]$x$get_labels()) else list(),
    status_labels=as.list(missing$status_label),context_rows=length(s$context_rows),zero_qualifications=as.list(zero_notes))
  artifacts[[length(artifacts)+1]]<-list(render_facts=surface,id=s$id,points=nrow(valid),unplotted_statuses=nrow(missing),
    log_intervals_not_drawn=nonpositive_intervals,axis_detail=axis_detail$audit,
    facet_scales=facet_scales,
    panel_y_ranges=lapply(ggplot_build(p)$layout$panel_params,function(z) unname(z$y.range)),
    panels=nlevels(d$panel),png=paste0(s$id,".png"),pdf=paste0(s$id,".pdf"),data=paste0(s$id,".plotted_rows.json"))
}
write_json(list(artifacts=artifacts,scientific_release=FALSE,stage="EV",model_calls=0),
 file.path(out,"manifest.json"),pretty=TRUE,auto_unbox=TRUE)
cat(length(artifacts),"supplemental source-native views rendered.\n")
