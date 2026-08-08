# Nagel (2012) daily reversal-return data

- Source set: `Nagel2012EvaporatingLiquidity`
- Artifact: official `allretout.csv` served from Stefan Nagel's Code & Data page for *Evaporating Liquidity*
- Verified file: `literature/papers/2012-Nagel2012EvaporatingLiquidityData-supplement-daily-reversal-returns.csv`
- SHA-256 and size: `2d75079d2df825ed363160ef5f9bafa9afe52ed0520d515d171fc1fc35acc8c7`; 65,901 bytes
- Inventory: 3,266 sorted unique trading dates from 9 January 1998 through 31 December 2010; four fields, `year ` with a trailing space, `month`, `day`, and `return`; CR-only line endings; no missing or nonfinite returns and no duplicate dates
- Scientific verification: mean 0.2966 percent per day, sample standard deviation 0.5558 percent, skewness 3.0246, Pearson kurtosis about 38.26 and minimum -3.8763 percent on 14 April 2000. These reproduce Table 1 Panel A's raw individual-stock transaction-price series after rounding.
- Discrepancy: the author page calls this the Figure 1 series and Figure 1's caption says factor-hedged, but the moments match the raw series, not Table 1 Panel B's hedged series. The file can reproduce the raw return history and approximately its moving average; exact Figure 1 reproduction still needs the market return and hedge coefficients.
- Reproduction boundary: no official code, VIX and control series, midpoint or industry returns, hedge inputs, sort assignments or output package was found. Full recreation also requires licensed CRSP plus external market and funding series.
- Disposition: preserve as an official partial data companion. It validates the raw reversal-return series but is not a complete replication package and does not identify observed provider returns, capital withdrawals or reallocation.
