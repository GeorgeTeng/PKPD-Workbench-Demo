# Vetted source-native display adapter. No generated code, joins or model fitting.
args <- commandArgs(trailingOnly=TRUE)
lib <- Sys.getenv('PKPD_R_LIB', unset='C:/Users/georg/Documents/Codex/ScienceEnv/R-library')
if (dir.exists(lib)) .libPaths(c(lib,.libPaths()))
if (!requireNamespace('jsonlite',quietly=TRUE)) stop('jsonlite is required')
if (identical(args,'--check')) {
  cat('EP_FULL_SOURCE_1.0: SOURCE_TABLE, SOURCE_XY_POINTS\n'); quit(status=0)
}
stopifnot(length(args)==3L, args[[1]] %in% c('ec','ev'))
input <- jsonlite::fromJSON(args[[2]],simplifyVector=FALSE)
stopifnot(identical(input$version,'EP_FULL_SOURCE_1.0'))
if (args[[1]]=='ec') {
  stopifnot(identical(input$scientific_release,FALSE))
  for (task in input$tasks) {
    stopifnot(task$operation_id %in% c('SOURCE_TABLE','SOURCE_XY_POINTS'))
    if (task$operation_id=='SOURCE_XY_POINTS') {
      for (p in task$plot$points) {
        rows <- Filter(function(r) identical(r$record_id,p$record_id),task$records)
        stopifnot(length(rows)==1L)
        row <- rows[[1]]
        for (role in c('x','y')) {
          column <- task$selection[[role]]
          stopifnot(identical(row$value_status[[column]],'QUANTIFIED'),
                    is.numeric(row$source_raw_values[[column]]),
                    isTRUE(all.equal(row$source_raw_values[[column]],p[[role]],tolerance=0)))
        }
      }
    }
  }
  result <- list(version='EP_FULL_SOURCE_1.0',tasks=input$tasks,computed_statistics=FALSE,scientific_release=FALSE)
  jsonlite::write_json(result,args[[3]],auto_unbox=TRUE,pretty=TRUE,digits=17,null='null',na='null')
} else {
  stopifnot(identical(input$computed_statistics,FALSE),identical(input$scientific_release,FALSE))
  esc <- function(v) {
    if (is.null(v)) return('null')
    s <- if (is.character(v)) v else as.character(v)
    s <- gsub('&','&amp;',s,fixed=TRUE); s <- gsub('<','&lt;',s,fixed=TRUE)
    s <- gsub('>','&gt;',s,fixed=TRUE); gsub('"','&quot;',s,fixed=TRUE)
  }
  out <- args[[3]]; artifacts <- list()
  for (task in input$tasks) {
    id <- task$task_id
    stopifnot(grepl('^TASK[0-9]{4,}$',id))
    table_name <- paste0(id,'.html'); rows_name <- paste0(id,'.plotted_rows.json')
    headers <- vapply(task$columns,function(c) paste0('<th>',esc(c$header),' [',esc(c$unit),']</th>'),character(1))
    content <- c('<!doctype html><html lang="en"><meta charset="utf-8"><style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px}small{display:block;color:#666}pre{white-space:pre-wrap}</style>',
      paste0('<h1>',esc(task$title),'</h1><p>',esc(task$experimental_unit),'</p>'),
      paste0('<p>',esc(task$context$reason),'</p><pre>',esc(paste(unlist(task$context$caption_limits),collapse='\n')),'</pre>'),
      paste0('<h2>Display annotations and operation limits</h2><pre>',esc(paste(unlist(c(task$context$annotations,task$context$operation_limitations)),collapse='\n')),'</pre>'),
      paste0('<table><tr><th>Source record</th>',paste(headers,collapse=''),'</tr>'))
    for (row in task$records) {
      cells <- vapply(task$columns,function(c) paste0('<td>',esc(row$source_raw_values[[c$id]]),
        '<small>',esc(row$value_status[[c$id]]),' · ',esc(row$source_cells[[c$id]]),'</small></td>'),character(1))
      content <- c(content,paste0('<tr><td>',esc(row$record_id),'</td>',paste(cells,collapse=''),'</tr>'))
    }
    content <- c(content,'</table>',paste0('<h2>Source notes and limits</h2><pre>',esc(task$notes),'</pre>'),
      '<p>Original values and statuses. Censored placeholders are not measured zeros. No new statistics, fitting, joins, or scientific release.</p>')
    image_name <- NULL
    if (task$operation_id=='SOURCE_XY_POINTS') {
      ps <- task$plot$points
      stopifnot(length(ps)>0L)
      x <- vapply(ps,function(p) p$x,numeric(1)); y <- vapply(ps,function(p) p$y,numeric(1))
      groups <- vapply(ps,function(p) p$group,character(1)); group_levels <- unique(groups)
      cols <- match(groups,group_levels)
      axis_label <- function(role) {
        c <- Filter(function(c) identical(c$id,task$selection[[role]]),task$columns)[[1]]
        paste0(c$header,' [',c$unit,']')
      }
      log_axes <- paste0(if(task$selection$x_scale=='log10') 'x' else '',if(task$selection$y_scale=='log10') 'y' else '')
      stopifnot(all(is.finite(x)),all(is.finite(y)))
      if (grepl('x',log_axes)) stopifnot(all(x>0))
      if (grepl('y',log_axes)) stopifnot(all(y>0))
      image_name <- paste0(id,'.png')
      caption <- paste(unlist(c(task$context$caption_limits,task$context$annotations,task$context$operation_limitations)),collapse='; ')
      caption_lines <- strwrap(caption,width=135)
      note_height <- max(1.5,0.18*length(caption_lines))
      png(file.path(out,image_name),width=1200,height=ceiling(800+120*note_height),res=120)
      layout(matrix(c(1,2),ncol=1),heights=c(6.7,note_height))
      par(mar=c(7,5,4,2))
      plot(x,y,pch=19,col=cols,log=log_axes,xlab=axis_label('x'),ylab=axis_label('y'),
           main=task$title,sub='Source-native points only; no trajectories, fitting or inferred uncertainty.')
      if (length(group_levels)>1 || (length(group_levels)==1 && nzchar(group_levels)))
        legend('topright',legend=group_levels,col=seq_along(group_levels),pch=19,bty='n',cex=0.8)
      mtext(paste0(length(task$plot$excluded),' source rows not plotted; see companion table and exclusion ledger.'),side=1,line=5,cex=0.8)
      par(mar=c(0,1,0,1)); plot.new()
      if (length(caption_lines)) text(0,0.98,paste(caption_lines,collapse='\n'),adj=c(0,1),cex=0.8)
      dev.off()
      content <- c(content,paste0('<img alt="Source-native points" src="',image_name,'">'))
    }
    content <- c(content,'</html>')
    writeLines(content,file.path(out,table_name),useBytes=TRUE)
    jsonlite::write_json(task$plot,file.path(out,rows_name),auto_unbox=TRUE,pretty=TRUE,digits=17,null='null')
    artifacts[[length(artifacts)+1L]] <- list(task_id=id,table=table_name,image=image_name,plotted_rows=rows_name)
  }
  jsonlite::write_json(list(version='EP_FULL_SOURCE_1.0',artifacts=artifacts,scientific_release=FALSE),
      file.path(out,'manifest.json'),auto_unbox=TRUE,pretty=TRUE,null='null')
}
