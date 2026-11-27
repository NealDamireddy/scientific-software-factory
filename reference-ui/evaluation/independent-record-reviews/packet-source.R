# Recreate the three unfiltered records with their original column names and order.
# The archived CSVs were generated with R and datasets version 4.5.2.
# Run Rscript --vanilla packet-source.R from this directory.
for (name in c("Formaldehyde", "ChickWeight", "attenu")) {
    records <- get(name, envir = asNamespace("datasets"))
    write.csv(as.data.frame(records), file.path("packet", paste0(name, ".csv")),
              row.names = FALSE, na = "")
}
