# Presentation only. Never transform, join, smooth or impute source values.
pkpd_theme <- function() {
  cowplot::theme_minimal_hgrid(font_size=12,font_family="sans")+
    theme(panel.grid.major.y=element_line(colour="#e4eaf0",linewidth=.3),
      panel.grid.minor=element_blank(),panel.border=element_rect(fill=NA,colour="#d4dfe8",linewidth=.4),
      strip.background=element_rect(fill="#edf3f7",colour=NA),
      strip.text=element_text(face="bold",size=10,colour="#22394b",margin=margin(7,5,7,5)),
      panel.spacing=grid::unit(1,"lines"),plot.title=element_text(face="bold",size=18,colour="#17364b"),
      plot.subtitle=element_text(size=11,colour="#4b6273",margin=margin(b=12)),
      plot.caption=element_text(hjust=0,size=9,colour="#4b6273",lineheight=1.15,margin=margin(t=12)),
      plot.title.position="plot",plot.caption.position="plot",
      axis.title=element_text(size=11),axis.text=element_text(colour="#334b5e"),
      legend.position="bottom",legend.title=element_blank(),
      plot.margin=margin(14,18,14,14))
}
pkpd_colours <- function(n) {
  base<-c("#0072B2","#D55E00","#009E73","#CC79A7","#E69F00","#56B4E9","#444444","#8C6D31")
  if(n<=length(base)) base[seq_len(n)] else grDevices::hcl.colors(n,"Dark 3")
}
pkpd_png <- function(path,width,height) ragg::agg_png(path,width=width,height=height,units="in",res=150,background="white")
pkpd_pdf <- function(path,width,height) grDevices::cairo_pdf(path,width=width,height=height,family="sans")


# Presentation only: change ticks, never observations, scale transforms or statuses.
pkpd_axis_detail <- function(p,d,policy) {
  sy<-p$scales$get_scales('y')
  if(is.null(sy)) {p<-p+scale_y_continuous();sy<-p$scales$get_scales('y')}
  log_y<-identical(sy$trans$name,'log-10')
  if(!sy$is_discrete()) {
    if(log_y) {
      sy$breaks<-function(limits) {
        v<-limits[is.finite(limits)&limits>0]
        if(!length(v)) return(numeric())
        e<-seq(floor(log10(min(v))),ceiling(log10(max(v))))
        # Keep wide log ranges readable; retain concentration-valued labels.
        if(length(e)>6L) return(10^e)
        sort(as.vector(outer(c(1,2,5),10^e)))
      }
    } else {
      sy$breaks<-function(limits) pretty(limits,n=10)
      sy$minor_breaks<-function(limits) {
        major<-pretty(limits,n=10)
        sort(unique(c(major,head(major,-1)+diff(major)/2)))
      }
    }
    p<-p+theme(panel.grid.minor.y=element_line(colour='#f0f3f6',linewidth=.2))
  }
  early<-numeric()
  if(!is.null(policy)&&isTRUE(policy$enabled)) {
    x<-d$x[is.finite(d$x)]
    sx<-p$scales$get_scales('x')
    if(is.null(sx)) {p<-p+scale_x_continuous();sx<-p$scales$get_scales('x')}
    if(length(unique(x))>1L&&!sx$is_discrete()&&identical(sx$trans$name,'identity')) {
      major<-pretty(range(x),n=6);step<-min(diff(major))
      # Only refine the early part of an actual time profile. No invented zero observation.
      positive<-x[x>0]
      if(length(positive)&&min(positive)<=step/2) early<-seq(0,step/2,length.out=5)
      sx$breaks<-function(limits) sort(unique(c(pretty(limits,n=6),early)))
      sx$minor_breaks<-NULL
      if(length(early)) p<-p+theme(axis.text.x=element_text(size=9,angle=45,hjust=1))
      p<-p+theme(panel.grid.major.x=element_line(colour='#f0f3f6',linewidth=.2))
    }
  }
  list(plot=p,audit=list(early_x_breaks=early,y_tick_policy=if(log_y) 'LOG_1_2_5' else 'PRETTY_10',
    coordinates_changed=FALSE,first_point_emphasis=FALSE,automatic_zoom=FALSE))
}

# Final label layout, after source-specific breaks/limits have been selected.
# Keep every time tick and coordinate; only its printed label/guide may change.
pkpd_time_axis_labels <- function(p,policy,width_inches=12) {
  audit<-list(applied=FALSE,coordinates_changed=FALSE)
  if(is.null(policy)||!isTRUE(policy$enabled)) return(list(plot=p,audit=audit))
  sx<-p$scales$get_scales('x')
  if(is.null(sx)||sx$is_discrete()||!identical(sx$trans$name,'identity')) return(list(plot=p,audit=audit))
  built<-ggplot_build(p);panel<-built$layout$panel_params[[1]]
  breaks<-panel$x$get_breaks();breaks<-breaks[is.finite(breaks)]
  if(length(breaks)<2L) return(list(plot=p,audit=audit))
  compact<-function(v) vapply(v,function(x) if(is.na(x)) NA_character_ else
    format(x,trim=TRUE,scientific=FALSE,digits=15),character(1))
  labels<-compact(breaks)
  # Conservative text-footprint estimate; two guide rows avoid crowding without
  # deleting early ticks, adding an inset or warping elapsed time.
  panel_mm<-max(1,(width_inches-2)*25.4)
  positions<-(breaks-panel$x.range[1])/diff(panel$x.range)*panel_mm
  text_mm<-nchar(labels)*9/72*25.4*.62
  overlaps<-function(rows,vertical=FALSE) {
    widths<-if(vertical) rep(9/72*25.4,length(labels)) else text_mm
    any(vapply(split(seq_along(breaks),(seq_along(breaks)-1L)%%rows),function(i) {
      if(length(i)<2L) return(FALSE)
      any(diff(positions[i]) < (head(widths[i],-1)+tail(widths[i],-1))/2+1.2)
    },logical(1)))
  }
  rows<-if(overlaps(1L)) 2L else 1L
  angle<-if(overlaps(rows)) 90 else 0
  sx$labels<-compact
  p<-p+guides(x=guide_axis(n.dodge=rows,angle=angle,check.overlap=FALSE))+
    theme(axis.text.x=element_text(size=9,angle=angle,hjust=if(angle==0) .5 else 1,vjust=.5))
  audit<-list(applied=TRUE,breaks=as.list(breaks),labels=as.list(labels),
    label_rows=rows,angle=angle,remaining_estimated_overlap=overlaps(rows,angle==90),
    coordinates_changed=FALSE,breaks_changed=FALSE,scale_changed=FALSE)
  list(plot=p,audit=audit)
}
