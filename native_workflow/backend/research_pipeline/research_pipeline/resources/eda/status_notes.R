# Presentation only: never substitute values or reinterpret source status.
pkpd_status_note <- function(d, categorical=FALSE, x_label="Time") {
  if(is.null(d)||nrow(d)==0) return("")
  labels<-if("status_label" %in% names(d)) d$status_label else d$status
  groups<-as.character(d$group)
  location<-if(categorical) as.character(d$category) else format(d$x,trim=TRUE,scientific=FALSE,digits=15)
  parts<-character()
  for(g in unique(groups)) {
    terms<-character()
    for(label in unique(labels[groups==g])) {
      ix<-which(groups==g & labels==label)
      places<-unique(location[ix])
      terms<-c(terms,paste0(label," at ",paste(places,collapse=", ")))
    }
    parts<-c(parts,paste0(g,": ",paste(terms,collapse="; ")))
  }
  paste0("Unplotted source statuses (",x_label,"): ",paste(parts,collapse=". "),". Full records retained in companion data.")
}
