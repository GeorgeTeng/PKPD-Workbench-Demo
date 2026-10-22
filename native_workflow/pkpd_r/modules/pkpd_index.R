run_pkpd_index <- function(request, output_dir) {
  options <- request$options
  mode <- options$mode %||% "compare_indices"
  if (mode == "compare_indices") {
    data <- records_frame(request$records)
    columns <- unlist(options$index_columns)
    response_column <- options$response_column %||% "response"
    id_column <- options$id_column %||% "unit_id"
    meta <- request$metadata
    for (key in c("drug", "data_origin", "response_unit", "endpoint_definition")) {
      value <- meta[[key]]
      if (is.null(value) || length(value)!=1 || !is.character(value) || value %in% c("", "NOT_FOUND"))
        stop(paste("Index comparison requires explicit metadata",key))
    }
    if (length(columns)<2 || anyDuplicated(columns)) stop("Supply at least two distinct index_columns.")
    windows <- list(); bases <- character()
    for (name in columns) {
      definition <- meta$index_definitions[[name]]
      if (is.null(definition) || is.null(definition$concentration_basis) || !definition$concentration_basis %in% c("free","total") ||
          is.null(definition$unit) || definition$unit %in% c("","NOT_FOUND")) stop(paste("Missing index definition:",name))
      w <- unlist(definition$window_h)
      assert_numeric(w,paste(name,"window_h"))
      if(length(w)!=2 || w[1]>=w[2]) stop("Index window must have two increasing endpoints.")
      windows[[name]] <- w; bases <- c(bases,definition$concentration_basis)
      if(definition$unit=="%" && any(data[[name]]<0 | data[[name]]>100)) stop("Percent index must be between 0 and 100.")
    }
    if(length(unique(bases))!=1 || !all(vapply(windows,function(w) isTRUE(all.equal(w,windows[[1]])),logical(1))))
      stop("This comparison requires the same concentration basis and time window across indices.")
    if("response_time_h" %in% names(data) && length(unique(data$response_time_h))!=1)
      stop("Use the same endpoint assessment time for all units.")
    comparison <- compare_pkpd_indices(data,columns,response_column,id_column,options$group_column,
      options$direction %||% "decreasing",options$estimate_hill %||% FALSE)
    ranking <- comparison$comparison
    y <- data[[response_column]]
    sst <- sum((y-mean(y))^2)
    if(!is.finite(sst) || sst<=0) stop("Response variation is required for R-squared.")
    ranking$R2 <- vapply(ranking$index,function(name) {
      fit <- comparison$models[[name]]
      if(is.null(fit)) NA_real_ else 1-sum((y-fit$predicted)^2)/sst
    },numeric(1))
    ranking$rank_R2 <- rank(-ranking$R2,ties.method="min",na.last="keep")
    ranking$rank_AIC <- rank(ranking$AIC,ties.method="min",na.last="keep")
    ranking$rank_AICc <- rank(ranking$AICc,ties.method="min",na.last="keep")
    ranking$rank_BIC <- rank(ranking$BIC,ties.method="min",na.last="keep")
    fitted <- which(ranking$status=="FITTED" & is.finite(ranking$R2) & is.finite(ranking$AIC))
    if(!length(fitted)) stop(paste("No candidate index could be fitted:",paste(ranking$reason,collapse="; ")))
    best_r2 <- ranking$index[fitted[abs(ranking$R2[fitted]-max(ranking$R2[fitted]))<1e-9]]
    best_aic <- ranking$index[fitted[abs(ranking$AIC[fitted]-min(ranking$AIC[fitted]))<1e-6]]
    aicc_valid <- which(is.finite(ranking$AICc))
    best_aicc <- if(length(aicc_valid)) ranking$index[aicc_valid[abs(ranking$AICc[aicc_valid]-min(ranking$AICc[aicc_valid]))<1e-6]] else character()
    ranking$delta_AIC <- ranking$AIC-min(ranking$AIC[fitted])
    ranking$delta_AICc <- if(length(aicc_valid)) ranking$AICc-min(ranking$AICc[aicc_valid]) else NA_real_
    bic_valid <- which(ranking$status=="FITTED" & is.finite(ranking$BIC))
    ranking$delta_BIC <- if(length(bic_valid)) ranking$BIC-min(ranking$BIC[bic_valid]) else NA_real_
    ranking$Akaike_weight <- NA_real_
    relative <- exp(-ranking$delta_AIC[fitted]/2)
    ranking$Akaike_weight[fitted] <- relative/sum(relative)
    ranking$AICc_weight <- NA_real_
    if(length(aicc_valid)) {
      relative_c <- exp(-ranking$delta_AICc[aicc_valid]/2)
      ranking$AICc_weight[aicc_valid] <- relative_c/sum(relative_c)
    }
    best_bic <- if(length(bic_valid)) ranking$index[bic_valid[abs(ranking$BIC[bic_valid]-min(ranking$BIC[bic_valid]))<1e-6]] else character()
    utils::write.csv(ranking,file.path(output_dir,"index_ranking.csv"),row.names=FALSE,na="")
    portable_models <- list()
    for (name in names(comparison$models)) {
      fit <- comparison$models[[name]]
      portable_models[[length(portable_models)+1L]] <- list(
        model_schema_version="1.0", family="endpoint_emax", index=name,
        theta=fit$theta, direction=fit$direction, estimate_hill=fit$estimate_hill,
        index_definition=meta$index_definitions[[name]], metadata=meta,
        parameters=fit$parameters, diagnostics=fit$diagnostics,
        warnings=as.list(fit$warnings),
        observed_index_range=range(data[[name]]),
        equation="response = E0 + sign * Emax * index^hill / (EC50^hill + index^hill); sign = -1 for decreasing, +1 for increasing")
    }
    for(j in seq_along(comparison$models))
      export_pkpd_fit(comparison$models[[j]],file.path(output_dir,"index_models",paste0("candidate_",j)),request$provenance)
    prediction <- data
    for(name in names(comparison$models)) prediction[[paste0("predicted_",name)]] <- comparison$models[[name]]$predicted
    utils::write.csv(prediction,file.path(output_dir,"index_predictions.csv"),row.names=FALSE)
    png(file.path(output_dir,"index_comparison.png"),width=600*length(columns),height=580,res=140)
    par(mfrow=c(1,length(columns)),mar=c(4.8,4.8,3.5,1),mgp=c(2.7,0.8,0))
    for(name in columns) {
      fit <- comparison$models[[name]]
      plot(data[[name]],y,pch=16,col="#34648888",xlab=paste0(name," (",meta$index_definitions[[name]]$unit,")"),
           ylab=paste0("Response (",meta$response_unit,")"),main=name)
      if(!is.null(fit)) {
        xx <- seq(min(data[[name]]),max(data[[name]]),length.out=200)
        lines(xx,predict_emax(fit,xx),col="#B34C26",lwd=2)
        row <- ranking[ranking$index==name,]
        mtext(sprintf("R2 = %.3f | AIC = %.2f",row$R2,row$AIC),side=3,line=0.2,cex=0.8)
      }
    }
    dev.off()
    return(list(ranking=ranking,selection=list(best_by_R2=as.list(best_r2),best_by_AIC=as.list(best_aic),
      best_by_AICc=as.list(best_aicc),best_by_BIC=as.list(best_bic),agreement_R2_AIC=setequal(best_r2,best_aic),
      status="PROPOSED_PENDING_HUMAN_REVIEW",all_candidates_fitted=all(ranking$status=="FITTED")),
      weight_interpretation="Relative support conditional on the same observations, likelihood and successfully fitted candidate set; not the probability an index is biologically correct. Missing AICc remains unavailable.",
      R2_definition="1 - SSE/SST on the original response scale; not squared Pearson correlation",
      comparison_basis="Same observations, endpoint, exposure window, total/free basis, direction, Hill setting and Gaussian response likelihood",
      model_definition=list(family="Emax/Hill",direction=options$direction %||% "decreasing",estimate_hill=options$estimate_hill %||% FALSE),
      models=portable_models,
      criterion_relationship="With the same n, parameter count and independent constant-variance Gaussian response errors, R2 and AIC rank SSE identically; their agreement is not independent validation.",
      index_correlation=comparison$index_correlation,fold_results=comparison$fold_results,
      interpretation="Highest training R2 and lowest AIC identify relative fit within these candidates, not external predictive reliability."))
  }
  if (mode == "endpoint_emax") {
    data <- records_frame(request$records)
    if (is.null(options$index_column)) stop("Specify index_column.")
    fit <- fit_index_emax(data, options$index_column, options$response_column %||% "response",
      options$id_column %||% "unit_id", options$direction %||% "decreasing", options$estimate_hill %||% FALSE)
    export_pkpd_fit(fit, file.path(output_dir, "endpoint_emax"), request$provenance)
    return(list(parameters = fit$parameters, diagnostics = fit$diagnostics, warnings = as.list(fit$warnings)))
  }
  if (is.null(options$mic_mg_L) || is.null(options$window_h)) stop("MIC and explicit window_h are required; no default MIC or 24-h window is assumed.")
  window <- unlist(options$window_h)
  basis <- options$output_basis %||% "free"
  fu <- options$fu
  rows <- list()
  if (mode == "profile") {
    data <- records_frame(request$records)
    required_columns(data, c("subject_id", "time_h", "concentration_mg_L"))
    for (id in unique(data$subject_id)) {
      d <- data[data$subject_id == id, ]
      z <- pkpd_indices(d$time_h, d$concentration_mg_L, options$mic_mg_L, window,
                       request$metadata, basis, fu, options$method %||% "linear_up_log_down")
      rows[[length(rows)+1L]] <- c(list(profile_id = id), z)
    }
  } else if (mode == "from_pk") {
    upstream <- request$upstream_result
    if (!identical(upstream$status, "SUCCEEDED") || !identical(upstream$module, "pk_longitudinal")) stop("Expected successful pk_longitudinal output envelope.")
    if (!length(upstream$result$models)) stop("Upstream PK output has no models.")
    for (m in upstream$result$models) {
      if (!identical(m$model_schema_version, "1.0") || !m$compartments %in% c(1L,2L)) stop("Unsupported portable PK model.")
      if (!identical(m$family, paste0(m$compartments,"_compartment_iv"))) stop("PK model family/compartments mismatch.")
      theta <- unlist(m$theta)
      expected <- if (m$compartments == 1L) c("CL","V") else c("CL","Vc","Q","Vp")
      if (!setequal(names(theta),expected)) stop("Portable PK parameters do not match the model.")
      assert_numeric(theta,"theta",positive=TRUE)
      meta <- m$metadata
      expected_basis <- if (meta$dose_unit == "mg/kg") "per_kg" else if (meta$dose_unit == "mg") "absolute" else "INVALID"
      if (m$parameter_basis != expected_basis || m$dose_coefficient_unit != meta$dose_unit) stop("Incompatible portable dose/parameter units.")
      doses <- if (!is.null(options$doses)) records_frame(options$doses) else records_frame(m$doses)
      if ("dose_mg_kg" %in% names(doses)) {
        if (meta$dose_unit != "mg/kg") stop("Dose-unit mismatch.")
        doses$dose_mg <- doses$dose_mg_kg
      }
      object <- list(type="individual_pk",theta=theta,compartments=m$compartments,doses=doses,meta=meta)
      z <- indices_from_pk_fit(object,options$mic_mg_L,window,fu,basis,options$step_h %||% 0.02)
      rows[[length(rows)+1L]] <- c(list(model_id=m$model_id, prediction_kind=m$prediction_kind,
        upstream_diagnostics=m$diagnostics, upstream_warnings=m$warnings),z)
    }
  } else stop("Unsupported pkpd_index mode.")
  write_pkpd_json(rows,file.path(output_dir,"indices.json"))
  list(indices=rows, interpretation="Point estimates conditional on input curves, model, MIC and fu. PK and MIC uncertainty is not propagated.")
}
