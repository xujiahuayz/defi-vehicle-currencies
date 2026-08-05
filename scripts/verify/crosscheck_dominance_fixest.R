# Independent cross-check of the headline dominance estimate in R's fixest.
#
# The Python estimate comes from pyfixest, a port of fixest's alternating-projections
# algorithm. Porting is exactly where a subtle disagreement would hide, and this
# session surfaced several bugs in my own code that each produced a plausible number,
# so the headline specification is re-estimated in the reference implementation.
# fixest is also what an empirical-finance referee recognises.
#
# R never enters the pipeline. It reads the same exported sample and writes into
# output/, matching the repo convention that code writes to output/ and papers read
# from it.
suppressMessages({library(fixest); library(data.table)})
args <- commandArgs(trailingOnly = TRUE)
# Transient interop file, NOT an artefact. It lives under data/interim/ rather than
# output/ because output/ holds paper-facing artefacts and this repository forbids
# delimited text there. R's arrow package is absent on this machine, so delimited text
# is the available handoff; the caller deletes it after the check.
infile <- if (length(args) >= 1) args[1] else "data/interim/hdfe_crosscheck_sample.tsv"
d <- fread(infile, sep = "\t")
cat(sprintf("rows %s | cells %s | pairs %s | native share %.3f | dominated %.3f\n",
            format(nrow(d), big.mark = ","), format(uniqueN(d$cell_id), big.mark = ","),
            format(uniqueN(d$pair_id), big.mark = ","), mean(d$native), mean(d$dominated)))
m <- feols(dominated ~ native | cell_id, data = d, cluster = ~pair_id)
s <- summary(m)
co <- coeftable(s)
cat(sprintf("\nfixest: coef %.6f  se %.6f  t %.3f  p %.3e\n",
            co["native", "Estimate"], co["native", "Std. Error"],
            co["native", "t value"], co["native", "Pr(>|t|)"]))
cat(sprintf("observations used %s | fixed effects absorbed %s\n",
            format(s$nobs, big.mark = ","), format(s$fixef_sizes[["cell_id"]], big.mark = ",")))
