# Rscript --vanilla verify.R /path/to/restored/archive
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 1L)
cycles <- data.frame(file = c("2005/VID_D.xpt", "2009/VID_F.xpt", "2013/VID_H.xpt"),
                     field = c("LBDVIDMS", "LBXVIDMS", "LBXVIDMS"),
                     count = c(8306, 8700, 8437), expected = c(56.8, 62.5, 62.4))
for (i in seq_len(nrow(cycles))) {
  d <- foreign::read.xport(file.path(args[1], cycles$file[i]))
  v <- d[[cycles$field[i]]]
  total <- sum(!is.na(v))
  median_value <- median(v, na.rm = TRUE)
  stopifnot(!anyDuplicated(d$SEQN), total == cycles$count[i], isTRUE(all.equal(median_value, cycles$expected[i])))
  cat(cycles$file[i], cycles$field[i], total, median_value, "nmol/L\n")
}
x <- d$LBXVIDMS[d$SEQN == 73557]
stopifnot(length(x) == 1L, isTRUE(all.equal(x, 28.9)))
cat("2013–14 record 73557:", x, "nmol/L\n")
