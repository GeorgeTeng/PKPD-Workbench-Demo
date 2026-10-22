# Source-bound PK/PD plotting templates. No extraction, fitting or imputation.
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==3L)
.libPaths(c(Sys.getenv('PKPD_R_LIB','C:/Users/georg/Documents/Codex/ScienceEnv/R-library'),.libPaths()))
suppressPackageStartupMessages(library(ggplot2))
library(jsonlite)
plan <- fromJSON(args[1], simplifyVector=FALSE)
input <- fromJSON(plan$input_ref$path, simplifyVector=FALSE)
out <- args[2];dir.create(out,recursive=TRUE,showWarnings=FALSE)
tables <- list()
for (task in input$tasks) {
  if (!is.null(tables[[task$dataset_id]])) stopifnot(identical(tables[[task$dataset_id]]$records,task$records))
  tables[[task$dataset_id]] <- task
}
`%or%` <- function(x,y) if(is.null(x)) y else x
val <- function(row,col) if(nzchar(col)) row$source_raw_values[[col]] else ''
quant <- function(row,col) nzchar(col)&&identical(row$value_status[[col]],'QUANTIFIED')&&is.numeric(val(row,col))&&length(val(row,col))==1L&&is.finite(val(row,col))
textval <- function(v) if(is.null(v)) 'NULL' else as.character(v)
wrap <- function(x,width=115) paste(strwrap(x,width=width),collapse='\n')
script_path <- sub("^--file=","",grep("^--file=",commandArgs(),value=TRUE)[1])
source(args[3])
source(file.path(dirname(script_path),"status_notes.R"))
base_theme <- pkpd_theme()
artifacts <- list(); all_sources <- list()
for (spec in plan$plots) {
  stopifnot(isTRUE(spec$standalone),length(spec$panels)==1L,
            is.character(spec$figure_index),nzchar(spec$figure_index),
            is.character(spec$x_label),nzchar(spec$x_label),is.character(spec$y_label),nzchar(spec$y_label))
  task_records <- function(did) {
    rr<-tables[[did]]$records; ids<-spec$record_scope[[did]]
    if(is.null(ids)) rr else Filter(function(r) r$record_id %in% unlist(ids),rr)
  }
  rows <- list(); excluded <- list(); status_rows <- list(); baseline <- list()
  add <- function(did,r,xcol,ycol,x,group,panel,xlabel='',errcol='',ncol='',basecol='') {
    ok <- quant(r,ycol); y <- if(ok) val(r,ycol) else NA_real_
    if(spec$y_scale=='log10' && ok && y<=0) {ok<-FALSE;y<-NA_real_}
    reason <- if(ok) '' else paste0(r$value_status[[ycol]] %or% 'ABSENT_STATUS',if(spec$y_scale=='log10') '; nonpositive also excluded' else '')
    z <- data.frame(dataset_id=did,record_id=r$record_id,x_column=xcol,y_column=ycol,x_cell=r$source_cells[[xcol]] %or% '',y_cell=r$source_cells[[ycol]] %or% '',
      x=x,y=y,group=group,panel=panel,x_label=xlabel,status=r$value_status[[ycol]] %or% 'ABSENT_STATUS',raw_y=textval(val(r,ycol)),
      error=if(nzchar(errcol)&&quant(r,errcol)) val(r,errcol) else NA_real_,error_column=errcol,error_cell=r$source_cells[[errcol]] %or% '',
      n=if(nzchar(ncol)&&quant(r,ncol)) val(r,ncol) else NA_real_,stringsAsFactors=FALSE)
    rows[[length(rows)+1L]] <<- z
    if(!ok) {
      excluded[[length(excluded)+1L]] <<- list(dataset_id=did,record_id=r$record_id,column=ycol,source_cell=r$source_cells[[ycol]],raw=val(r,ycol),status=r$value_status[[ycol]],reason=reason)
      status_rows[[length(status_rows)+1L]] <<- data.frame(x=x,group=group,status=if(spec$y_scale=='log10' && quant(r,ycol) && val(r,ycol)<=0) paste0(z$status,': nonpositive source value; not on log axis') else z$status,panel=panel)
    }
    if(nzchar(basecol)&&quant(r,basecol)) baseline[[length(baseline)+1L]] <<- data.frame(dataset_id=did,record_id=r$record_id,source_cell=r$source_cells[[basecol]],panel=panel,y=val(r,basecol))
  }
  if(spec$kind %in% c('summary_profile','source_id_profile','independent_points')) {
    for(panel in spec$panels) for(s in panel$series) {
      task <- tables[[s$dataset_id]]
      if(spec$kind=='summary_profile') stopifnot(grepl('mean',task$title,ignore.case=TRUE))
      if(spec$kind=='source_id_profile') stopifnot(grepl('Join within source file and ID',task$notes,fixed=TRUE))
      for(r in task_records(task$dataset_id)) {
        if(spec$kind=='source_id_profile' && !identical(as.numeric(val(r,'c003_amt_cmt')),1)) next
        stopifnot(quant(r,s$x))
        group <- s$label
        if(nzchar(s$group)) {
          gid <- val(r,s$group);group<-paste0(s$label,' ',textval(gid))
          if(spec$kind=='source_id_profile') {
            events<-Filter(function(e) identical(val(e,s$group),gid)&&quant(e,'c002_amt')&&identical(as.numeric(val(e,'c003_amt_cmt')),2),task$records)
            stopifnot(length(events)==1L)
            group<-paste0(format(val(events[[1]],'c002_amt'),scientific=val(events[[1]],'c002_amt')<.001,trim=TRUE),' mg/L | ID ',textval(gid))
          }
        }
        add(s$dataset_id,r,s$x,s$y,val(r,s$x),group,panel$label,panel$x_label %or% '')
      }
    }
  } else if(spec$kind=='categorical_raw') {
    for(panel in spec$panels) {
      task<-tables[[panel$dataset_id]];lev<-unique(vapply(task$records,function(r) textval(val(r,panel$group_column)),character(1)))
      stopifnot(length(lev)==3L,grepl('pre-treatment',lev[1],ignore.case=TRUE),
                grepl('vehicle|veichle|control',lev[2],ignore.case=TRUE),grepl('polymyxin|PMB',lev[3],ignore.case=TRUE))
      for(r in task_records(task$dataset_id)) for(col in panel$value_columns) {
        label<-textval(val(r,panel$group_column));xi<-match(label,lev)
        # A deterministic visual offset in categorical space, never a measured coordinate.
        offset<-(match(col,panel$value_columns)-(length(panel$value_columns)+1)/2)*.055
        display_group<-if(xi==2L) 'Vehicle/control' else label
        add(panel$dataset_id,r,panel$group_column,col,xi+offset,display_group,panel$label,label)
      }
    }
  } else if(spec$kind=='reported_interval') {
    for(s in spec$panels) for(r in task_records(s$dataset_id)) {
      stopifnot(quant(r,s$x));label<-textval(val(r,s$facet))
      if(nzchar(s$unit_column)) label<-paste0(label,' [',textval(val(r,s$unit_column)),']')
      add(s$dataset_id,r,s$x,s$y,val(r,s$x),if(nzchar(s$group)) textval(val(r,s$group)) else spec$error_type,label,
          errcol=s$error,ncol=s$n,basecol=s$baseline)
    }
  } else if(spec$kind=='frequency_bars') {
    s<-spec$panels[[1]];task<-tables[[s$dataset_id]]
    for(i in seq_along(task$records)) {r<-task$records[[i]];add(s$dataset_id,r,s$x,s$y,i,'Reported percentage',s$label,textval(val(r,s$x)))}
  } else stop('Unsupported template')
  d<-do.call(rbind,rows);stopifnot(nrow(d)>0)
  d$panel<-factor(d$panel,levels=unique(d$panel));d$group<-factor(d$group,levels=unique(d$group))
  stopifnot(nlevels(d$panel)==1L)
  d$segment<-'';segments<-list()
  if(spec$kind %in% c('summary_profile','source_id_profile')) {
    for(ix in split(seq_len(nrow(d)),interaction(d$panel,d$dataset_id,d$group,drop=TRUE))) {
      ix<-ix[order(d$x[ix])];segment<-1L;previous<-NULL
      # Tied times are ambiguous: retain points but do not create an arbitrary path.
      if(anyDuplicated(d$x[ix])) next
      for(i in ix) {
        if(is.na(d$y[i])) {previous<-NULL;segment<-segment+1L;next}
        d$segment[i]<-paste(d$panel[i],d$dataset_id[i],d$group[i],segment,sep='|')
        if(!is.null(previous)) segments[[length(segments)+1L]]<-list(dataset_id=d$dataset_id[i],from_record=d$record_id[previous],to_record=d$record_id[i],x_column=d$x_column[i],y_column=d$y_column[i],group=as.character(d$group[i]),panel=as.character(d$panel[i]),semantics='DESCRIPTIVE_GUIDE_NOT_MODEL_FIT')
        previous<-i
      }
    }
  }
  p<-ggplot(d,aes(x=x,y=y,colour=group))
  if(spec$kind %in% c('summary_profile','source_id_profile')) {
    line_data<-d[nzchar(d$segment)&!is.na(d$y),];
    valid<-names(which(table(line_data$segment)>1));line_data<-line_data[line_data$segment %in% valid,]
    p<-p+geom_line(data=line_data,aes(group=segment),linewidth=.6,alpha=.8)+geom_point(size=2,na.rm=TRUE)
  } else if(spec$kind=='reported_interval') {
    stopifnot(all(d$error[!is.na(d$error)]>=0))
    p<-p+geom_errorbar(aes(ymin=y-error,ymax=y+error),width=0,linewidth=.6,na.rm=TRUE)+geom_point(size=2.5,na.rm=TRUE)
    if(any(!is.na(d$n))) p<-p+geom_text(aes(label=ifelse(is.na(n),'',paste0('n=',n))),vjust=-1,hjust=-.1,size=2.8,show.legend=FALSE,na.rm=TRUE)
    if(length(baseline)) {
      b<-unique(do.call(rbind,baseline)[c('panel','y')]);stopifnot(!anyDuplicated(b$panel))
      p<-p+geom_hline(data=b,aes(yintercept=y),inherit.aes=FALSE,colour='#777777',linetype='dashed',linewidth=.5)
    }
  } else if(spec$kind=='frequency_bars') p<-p+geom_col(aes(fill=group),colour=NA,width=.75)+scale_fill_manual(values=pkpd_colours(nlevels(d$group)),name='Series / group')+geom_text(aes(label=y),vjust=-.5,colour='#243746',size=3)
  else p<-p+geom_point(size=2.3,alpha=.85,na.rm=TRUE)
  scales<-if(spec$kind %in% c('reported_interval','summary_profile')) 'free_y' else if(spec$kind=='independent_points') 'free_x' else 'fixed'
  if(spec$kind=='source_id_profile' && !length(status_rows)) spec$caption<-sub('Censored coordinates are not plotted; see status strip.',
    'No censored or missing observation responses occur in this supplied series.',spec$caption,fixed=TRUE)
  if(spec$kind %in% c('reported_interval','summary_profile') && nlevels(d$panel)>1) spec$caption<-paste(spec$caption,'Panel Y ranges differ; do not compare heights across different units or matrices.')
  spec$caption<-gsub("see status strip", "see status note", spec$caption,fixed=TRUE)
  p<-p+
    scale_colour_manual(values=if(!is.null(spec$palette_index)&&nlevels(d$group)==1L) pkpd_colours(3)[[spec$palette_index]] else pkpd_colours(nlevels(d$group)))+
    labs(title=wrap(paste(spec$figure_index,spec$title,sep=' | '),78),subtitle=wrap(spec$subtitle,95),x=spec$x_label,y=spec$y_label,colour=spec$legend_title %or% 'Series / group',caption=wrap(spec$caption))+base_theme+theme(legend.title=element_text(size=10))
  if(identical(spec$x_scale,'log10')) {
    stopifnot(!spec$kind %in% c('categorical_raw','frequency_bars'),all(is.finite(d$x)),all(d$x>0))
    p<-p+scale_x_log10()
  }
  if(spec$y_scale=='log10') {stopifnot(all(d$y[!is.na(d$y)]>0));p<-p+scale_y_log10()}
  else p<-p+scale_y_continuous(expand=expansion(mult=c(.08,.18)))
  if(spec$kind=='categorical_raw') {
    p<-p+scale_x_continuous(breaks=1:3,labels=c('Pre-treatment\n0 h','Vehicle/control\n24 h','PMB\n24 h'))
  }
  if(spec$kind=='reported_interval') p<-p+scale_x_continuous(breaks=sort(unique(d$x)))
  if(spec$kind=='frequency_bars') p<-p+scale_x_continuous(breaks=d$x,labels=d$x_label)
  if(spec$kind=='independent_points') p<-p+theme(legend.position='bottom')
  axis_detail<-pkpd_axis_detail(p,d,spec$axis_detail %or% spec$first_observation)
  p<-axis_detail$plot
  time_labels<-pkpd_time_axis_labels(p,spec$axis_detail %or% spec$first_observation,width_inches=10.5)
  p<-time_labels$plot
  axis_detail$audit$time_labels<-time_labels$audit
  sd<-if(length(status_rows)) do.call(rbind,status_rows) else NULL
  status_note<-pkpd_status_note(sd,FALSE,spec$x_label)
  if(!is.null(spec$study_annotations)) {
    actual_ids<-vapply(excluded,function(z) z$record_id,character(1))
    stopifnot(identical(as.character(unlist(spec$study_annotations$status_record_ids)),as.character(actual_ids)))
    status_note<-spec$study_annotations$status_note
    stopifnot(nzchar(status_note)==(length(actual_ids)>0))
  }
  if(nzchar(status_note)) p<-p+labs(caption=paste(p$labels$caption,wrap(status_note),sep="\n"))
  height<-max(5.5,3.1*ceiling(nlevels(d$panel)/spec$ncol)+2)
  height<-height+max(0,length(strsplit(p$labels$title,'\n',fixed=TRUE)[[1]])-1)*.25
  height<-height+max(0,length(strsplit(p$labels$subtitle,'\n',fixed=TRUE)[[1]])-1)*.18
  height<-height+max(0,length(strsplit(p$labels$caption,"\n",fixed=TRUE)[[1]])-4)*.16
  draw<-function() print(p)
  pkpd_png(file.path(out,paste0(spec$id,'.png')),width=10.5,height=height);draw();dev.off()
  pkpd_pdf(file.path(out,paste0(spec$id,'.pdf')),width=10.5,height=height);draw();dev.off()
  write.csv(d,file.path(out,paste0(spec$id,'.plotted_rows.csv')),row.names=FALSE,na='')
  write_json(d,file.path(out,paste0(spec$id,'.plotted_rows.json')),dataframe='rows',pretty=TRUE,auto_unbox=TRUE,digits=17,null='null',na='null')
  rendered_scale<-function(axis) {
    sc<-p$scales$get_scales(axis)
    if(is.null(sc)||sc$is_discrete()) return('linear')
    if(identical(sc$trans$name,'log-10')) 'log10' else 'linear'
  }
  write_json(list(plot_id=spec$id,excluded=excluded,segments=segments,baseline=baseline,scientific_release=FALSE,rendered_scales=list(x=rendered_scale('x'),y=rendered_scale('y')),axis_detail=axis_detail$audit,presentation=list(standalone=TRUE,figure_index=spec$figure_index,x_label=spec$x_label,y_label=spec$y_label,legend_groups=levels(d$group))),
             file.path(out,paste0(spec$id,'.audit.json')),pretty=TRUE,auto_unbox=TRUE,digits=17,null='null',na='null')
  built<-ggplot_build(p)
  geoms<-vapply(p$layers,function(z) class(z$geom)[1],character(1))
  count_geom<-function(name) sum(vapply(which(geoms==name),function(i) sum(!is.na(built$data[[i]]$y)),integer(1)))
  elements<-c(if(count_geom('GeomPoint')>0) 'POINTS',if(length(segments)>0) 'CONNECTING_LINES',
    if(count_geom('GeomErrorbar')>0) 'ERROR_BARS',if(count_geom('GeomCol')>0) 'BARS',if(nzchar(status_note)) 'STATUS_TEXT')
  surface<-list(status_display="caption",status_note=status_note,status_y=list(),status_count=length(status_rows),elements=as.list(elements),point_count=count_geom('GeomPoint'),line_segments=length(segments),
    figure_index=spec$figure_index,x_label=p$labels$x,y_label=p$labels$y,panels=length(built$layout$panel_params))
  artifacts[[length(artifacts)+1L]]<-list(render_facts=surface,id=spec$id,kind=spec$kind,png=paste0(spec$id,'.png'),pdf=paste0(spec$id,'.pdf'),
    data=paste0(spec$id,'.plotted_rows.json'),csv=paste0(spec$id,'.plotted_rows.csv'),audit=paste0(spec$id,'.audit.json'),dataset_ids=unique(d$dataset_id),
    points=sum(!is.na(d$y)),excluded=length(excluded),guide_segments=length(segments),panels=nlevels(d$panel))
}
write_json(list(version=plan$version,artifacts=artifacts,R=R.version.string,ggplot2=as.character(packageVersion('ggplot2')),
               computed_new_statistics=FALSE,model_calls=0,scientific_release=FALSE),file.path(out,'manifest.json'),pretty=TRUE,auto_unbox=TRUE,digits=17)
cat(length(artifacts),'publication-style source-bound figures rendered.\n')
