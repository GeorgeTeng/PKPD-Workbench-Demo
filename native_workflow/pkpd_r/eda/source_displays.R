# Deterministic rendering of audited source-native projections. No model or EC call.
args <- commandArgs(trailingOnly=TRUE)
.libPaths(c("C:/Users/georg/Documents/Codex/ScienceEnv/R-library",.libPaths()))
suppressPackageStartupMessages(library(ggplot2))
library(jsonlite)
plan <- fromJSON(args[1],simplifyVector=FALSE)
out <- args[2]; dir.create(out,recursive=TRUE,showWarnings=FALSE)
`%or%` <- function(x,y) if(is.null(x)) y else x
script_path <- sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1])
source(file.path(dirname(normalizePath(script_path)),"plot_style.R"))
theme_source <- pkpd_theme()
artifacts <- list()
for (s in plan$plots) {
  stopifnot(isTRUE(s$standalone),is.character(s$figure_index),nzchar(s$figure_index),
            is.character(s$x_label),nzchar(s$x_label),is.character(s$y_label),nzchar(s$y_label))
  rows <- lapply(s$rows,function(r) data.frame(
    dataset_id=r$dataset_id,record_id=r$record_id,y_column=r$y_column,
    x=r$x,y=r$y %or% NA_real_,error=r$error %or% NA_real_,n=r$n %or% NA_real_,
    panel=r$panel,group=r$group,category=r$category,bound=r$bound,
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
  } else p <- p+geom_point(size=2.5,alpha=.9)
  if(any(!is.na(valid$n))) p<-p+geom_text(aes(y=y+error,label=paste0("n=",n)),vjust=-.7,size=3,show.legend=FALSE)
  p<-p+
    labs(title=paste(s$figure_index,s$title,sep=" | "),subtitle=s$question,x=s$x_label,y=s$y_label,colour="Series / group",shape="Status",
     caption=paste(strwrap(s$caption,width=125),collapse="\n"))+theme_source+theme(legend.title=element_text(size=10))
  if(s$scale=="log10") {
    stopifnot(all(valid$y>0));p<-p+scale_y_log10(expand=expansion(mult=c(.12,.22)))
  } else p<-p+scale_y_continuous(expand=expansion(mult=c(.1,.2)))
  if(s$categorical) p<-p+scale_x_discrete(labels=function(x) sub("^T[0-9]+ \\| ","",x))+
    theme(axis.text.x=element_text(angle=35,hjust=1,size=9))
  p<-p+scale_colour_manual(values=pkpd_colours(nlevels(d$group)))
  
  if(!s$categorical) p<-p+scale_x_continuous(n.breaks=4)
  p<-p+theme(legend.position="bottom")
  axis_detail<-pkpd_axis_detail(p,d,s$axis_detail %or% s$first_observation)
  p<-axis_detail$plot
  missing<-d[is.na(d$y) | !d$eligible,];strip<-NULL
  if(nrow(missing)) {
    missing$status<-ifelse(nzchar(missing$exclusion),paste(missing$status,missing$exclusion,sep=": "),missing$status)
    missing$source_slot<-ifelse(as.character(missing$panel)==as.character(missing$group),as.character(missing$panel),paste(missing$panel,missing$group,sep=" | "))
    strip<-ggplot(missing,aes(x=x,y=source_slot,shape=status))+geom_point(size=2.5,colour="#b34843")+
      labs(x=s$x_label,y="Source series / status",title="Unplotted source statuses (no response coordinate)",shape=NULL)+
      theme_source+theme(plot.title=element_text(size=11),axis.text.y=element_text(size=8))
    strip<-strip+scale_x_continuous(limits=range(d$x),n.breaks=4)
  }
  h<-max(6,2.8*ceiling(nlevels(d$panel)/s$ncol)+2.3)
  sh<-if(is.null(strip)) 0 else max(1.8,.23*length(unique(missing$source_slot))+1.4)
  draw<-function() {
    if(is.null(strip)) print(p) else {
      print(patchwork::wrap_plots(p,strip,ncol=1,heights=c(h,sh)))
    }
  }
  pkpd_png(file.path(out,paste0(s$id,".png")),width=12,height=h+sh);draw();dev.off()
  pkpd_pdf(file.path(out,paste0(s$id,".pdf")),width=12,height=h+sh);draw();dev.off()
  # Exact records, including raw compound text, status and bound semantics.
  write_json(s$rows,file.path(out,paste0(s$id,".plotted_rows.json")),pretty=TRUE,auto_unbox=TRUE,digits=17,null="null")
  artifacts[[length(artifacts)+1]]<-list(id=s$id,points=nrow(valid),unplotted_statuses=nrow(missing),
    log_intervals_not_drawn=nonpositive_intervals,axis_detail=axis_detail$audit,
    panels=nlevels(d$panel),png=paste0(s$id,".png"),pdf=paste0(s$id,".pdf"),data=paste0(s$id,".plotted_rows.json"))
}
write_json(list(artifacts=artifacts,scientific_release=FALSE,stage="EV",model_calls=0),
 file.path(out,"manifest.json"),pretty=TRUE,auto_unbox=TRUE)
cat(length(artifacts),"supplemental source-native views rendered.\n")
