# Token-level test: forced-route intensity and exit from Uniswap V1

### Sample construction

| filter | exchanges | share kept |
|---|---|---|
| V1 exchanges with any pre-window activity | 1,496 | 1.000 |
| pre-window ETH-paired legs >= 50 | 261 | 0.174 |
| traded ETH-paired within 30 days of the event | 247 | 0.165 |
| nonzero pre-window ETH-paired volume, i.e. not dust-only | 247 | 0.165 |
| pool size resolved and positive at the event | 247 | 0.165 |

Pool-size resolution rate at the event date: 100.0% of the exchanges that reach that step; 0 had no daily snapshot inside the 30-day window and are dropped rather than imputed.

Units: **247 V1 exchanges**, each contributing one spell measured over 24 thirty-day months from 2020-05-05. Forced-route intensity: mean 0.189, median 0.142, standard deviation 0.167, interquartile range 0.074 to 0.258, maximum 0.924. Share with any forced-route leg: 98.0%.

### Covariate balance, forced-route intensity above versus below its median

| covariate | high-intensity median | low-intensity median | high mean | low mean | normalised difference |
|---|---|---|---|---|---|
| pre-V2 ETH-paired legs | 267.000 | 323.000 | 4,097.618 | 2,454.266 | 0.138 |
| pre-V2 ETH-paired volume, ETH | 77.368 | 95.545 | 22,945 | 5,806.955 | 0.218 |
| pool size at the event, ETH | 35.184 | 14.253 | 1,699.612 | 767.915 | 0.153 |
| age in days at the event | 230.000 | 177.500 | 260.894 | 237.274 | 0.141 |
| active days in the pre-window | 104.000 | 68.000 | 107.081 | 85.435 | 0.369 |
| distinct forced-route counterparties | 25.000 | 7.000 | 44.870 | 21.702 | 0.555 |
| log pre-window activity trend | -0.254 | -0.268 | 0.283 | 0.277 | 0.003 |

Forced-route intensity has correlation -0.012 with log pre-V2 ETH-paired legs and +0.161 with log pool size, so the headline threat that intensity is simply a label for small peripheral tokens is not what the data show on size, though it is mildly present on depth.

### Exit definitions and how many exchanges actually exit

| outcome | exits observed | of units | right-censored | median months to exit | mean months |
|---|---|---|---|---|---|
| ETH-paired legs below 10% of the pre-V2 baseline | 241 | 247 | 6 | 4.00 | 6.17 |
| ETH-paired legs below an absolute floor of 3 a month | 216 | 247 | 31 | 4.00 | 8.95 |
| ALL legs below 10% of the pre-V2 baseline (mechanically contaminated) | 241 | 247 | 6 | 4.00 | 6.03 |

### Log survival time on forced-route intensity

A NEGATIVE coefficient is the mandate hypothesis: more forced-route intensity, faster exit. Standard errors are heteroskedasticity-robust, which is what a variance clustered on the exchange collapses to when each exchange contributes one spell.

| outcome | controls | n | forced_share | robust se | t | per SD of intensity | R2 |
|---|---|---|---|---|---|---|---|
| ETH-paired, relative threshold | no controls | 247 | 1.0617 | 0.2958 | 3.5895 | 0.1778 | 0.0375 |
| ETH-paired, relative threshold | size only | 247 | 0.7954 | 0.3006 | 2.6458 | 0.1332 | 0.1381 |
| ETH-paired, relative threshold | full | 247 | 0.2600 | 0.3226 | 0.8060 | 0.0435 | 0.2869 |
| ETH-paired, absolute floor | no controls | 247 | 1.0343 | 0.3246 | 3.1862 | 0.1732 | 0.0277 |
| ETH-paired, absolute floor | size only | 247 | 0.8273 | 0.2800 | 2.9549 | 0.1385 | 0.3510 |
| ETH-paired, absolute floor | full | 247 | 0.2761 | 0.3074 | 0.8982 | 0.0462 | 0.4712 |
| all legs, relative threshold | no controls | 247 | 0.4730 | 0.3135 | 1.5089 | 0.0792 | 0.0077 |
| all legs, relative threshold | size only | 247 | 0.2183 | 0.3164 | 0.6900 | 0.0366 | 0.0969 |
| all legs, relative threshold | full | 247 | -0.3049 | 0.3388 | -0.8999 | -0.0511 | 0.2449 |

The specification to read is the absolute-floor outcome with full controls, because it is the only one in which neither the treatment nor the exit threshold is a function of the other. It gives **+0.276 log-months per unit of forced-route intensity, robust standard error 0.307, t = +0.90**, on 247 exchanges. Scaled to one standard deviation of intensity (0.167) the point estimate is +0.046 log-months with a 95% interval of [-0.055, +0.147], i.e. a survival-time ratio between 0.95 and 1.16. Comparing an exchange at the 95th percentile of intensity (0.54) with one at the 5th (0.02), a spread of 0.52, the interval on the survival-time ratio is [0.84, 1.59]. The point estimate has the WRONG sign for the mandate hypothesis and is not significant, and it is reported that way rather than as an absence of a relationship.

The sign pattern across the three outcome definitions is itself the diagnostic. Without controls, intensity predicts LONGER survival on both own-flow outcomes, which is the wrong sign for the hypothesis and is partly arithmetic on the relative-threshold outcome, since for a given total activity a higher forced share means a smaller ETH-paired baseline and therefore a lower exit threshold. On the total-legs outcome the sign flips negative once controls are added, and that is the outcome in which the treatment mechanically removes part of the dependent variable. Neither sign survives at conventional significance.

### Shape of the dose-response, which is what decides the wrong-signed result

A single dichotomy at the median gives a coefficient that clears significance with the WRONG sign, so it has to be reported and then read against the shape of the relationship it summarises. Intensity quintiles enter with the same controls, quintile 1 as the reference:

| intensity quintile | exchanges | mean forced share | log survival vs quintile 1 | robust se |
|---|---|---|---|---|
| 1 | 50 | 0.0289 | 0.0000 |  |
| 2 | 49 | 0.0866 | 0.0090 | 0.1648 |
| 3 | 49 | 0.1431 | 0.4446 | 0.1647 |
| 4 | 49 | 0.2260 | 0.2875 | 0.1647 |
| 5 | 50 | 0.4574 | 0.1374 | 0.1675 |

Above-median intensity against below-median, with the full controls: **+0.2221 log-months, robust standard error 0.1034, t = +2.15** on 247 exchanges. That is a significant estimate of the wrong sign, and it is reported as one. It is not, however, a dose-response. The quintile profile is hump-shaped rather than monotone, with the most heavily forced quintile (mean intensity 0.457) sitting closer to the reference than quintiles 2 and 3 do, and the joint Wald test on the four quintile dummies is 11.22 on 4 degrees of freedom, p = 0.024. A monotone effect of intensity cannot produce that pattern, and the median dichotomy is significant only because it happens to pool the middle of the distribution with the top. The continuous specification, which is the pre-specified dose-response, is the one to read.

### Intensity against breadth, which is where the sign lives

Forced-route intensity and forced-route BREADTH, the number of distinct counterparty exchanges an exchange was routed to or from in the pre-window, are correlated at +0.362, and the median high-intensity exchange has 25 counterparties against 7 for the median low-intensity one. Breadth is a popularity measure: an exchange reachable from many others is one many traders wanted. Adding it changes the answer.

| specification | treatment coefficient | robust se | t | routing breadth coefficient | t on breadth | R2 |
|---|---|---|---|---|---|---|
| intensity, pre-specified controls | 0.2761 | 0.3074 | 0.8982 |  |  | 0.4712 |
| intensity, plus routing breadth | -0.5311 | 0.3276 | -1.6210 | 0.3565 | 3.5036 | 0.5048 |
| above-median intensity, pre-specified controls | 0.2221 | 0.1034 | 2.1476 |  |  | 0.4801 |
| above-median intensity, plus routing breadth | -0.0003 | 0.1209 | -0.0026 | 0.2894 | 2.6714 | 0.5006 |

The wrong-signed coefficient is breadth, not intensity. Holding counterparty breadth fixed, continuous intensity turns NEGATIVE, which is the direction the mandate hypothesis predicts, at -0.5311 with a robust standard error of 0.3276 (t = -1.62), and the significant median dichotomy collapses to -0.0003 (t = -0.00). Every intensity quintile dummy turns negative too, with a joint Wald statistic of 10.68 on 4 degrees of freedom, p = 0.030. This specification is reported and is NOT promoted to primary, for a reason that has to be stated: breadth is itself a function of the treatment, since an exchange with no forced routes has no counterparties, so conditioning on it partials out part of the object being measured. It is a decomposition of forced routing into intensity and reach, not a cleaner identification of intensity. What it establishes is that the SIGN of the token-level estimate is not identified: it is positive under the pre-specified controls, negative under a defensible addition to them, and significant under neither.

### Grouped-time proportional hazard, exchange-month panel

Here a POSITIVE coefficient is the mandate hypothesis. This is the one specification in which clustering has content, because a unit contributes many rows, and the standard errors are clustered on the exchange.

| outcome | exchange-months | clusters | failures | forced_share | cluster-robust se | t | hazard ratio per SD |
|---|---|---|---|---|---|---|---|
| ETH-paired, relative threshold | 1,772 | 247 | 241 | 0.1404 | 0.4352 | 0.3227 | 1.0238 |
| ETH-paired, absolute floor | 2,457 | 247 | 216 | 0.0257 | 0.4306 | 0.0596 | 1.0043 |
| all legs, relative threshold | 1,737 | 247 | 241 | 0.7389 | 0.4768 | 1.5498 | 1.1317 |

### Within-stratum comparison, size quintile crossed with depth tercile

| stratum | units | high-intensity | low-intensity | mean log survival, high | mean log survival, low | difference |
|---|---|---|---|---|---|---|
| 0|0 | 30 | 13 | 17 | 0.942 | 0.873 | 0.069 |
| 0|1 | 17 | 8 | 9 | 1.454 | 1.414 | 0.040 |
| 0|2 | 4 | 1 | 3 | 2.565 | 1.561 | 1.004 |
| 1|0 | 23 | 12 | 11 | 1.558 | 1.274 | 0.284 |
| 1|1 | 20 | 11 | 9 | 1.951 | 1.244 | 0.708 |
| 1|2 | 5 | 4 | 1 | 2.220 | 3.219 | -0.998 |
| 2|0 | 18 | 9 | 9 | 1.061 | 1.458 | -0.397 |
| 2|1 | 20 | 10 | 10 | 2.170 | 1.302 | 0.869 |
| 2|2 | 11 | 6 | 5 | 2.224 | 1.776 | 0.448 |
| 3|0 | 6 | 1 | 5 | 3.219 | 1.303 | 1.916 |
| 3|1 | 19 | 12 | 7 | 2.584 | 1.902 | 0.682 |
| 3|2 | 24 | 11 | 13 | 2.597 | 2.054 | 0.544 |
| 4|2 | 38 | 25 | 13 | 2.835 | 2.933 | -0.099 |

Strata containing both a high- and a low-intensity exchange: 13 of 15, holding **235 of 247 exchanges**. Those are the units that identify the stratified estimate; the rest contribute nothing to it. Unit-weighted difference in mean log survival time, high minus low intensity: **+0.3037**. As a stratum-fixed-effects regression on the same units the coefficient is **+0.2965** with a robust standard error of 0.1160 (t = +2.56); adding the continuous controls on top of the strata leaves it at +0.2678 (se 0.1053, t = +2.54). Replacing the dichotomy with continuous intensity in the same specification gives +0.3283 (se 0.3150, t = +1.04). Matching on size and depth therefore does not rescue the dichotomy's significance for a dose-response reading: the continuous version of the same comparison is indistinguishable from zero.

### Randomisation inference on the forced-share coefficient

| null | draws | sd of placebo coefficient | two-sided p for the point estimate |
|---|---|---|---|
| unrestricted | 5,000 | 0.2979 | 0.3554 |
| within size quintile | 5,000 | 0.2988 | 0.3586 |

### Robustness of the primary estimate

| variant | n | exits | forced_share | robust se | t |
|---|---|---|---|---|---|
| baseline | 247 | 216 | 0.2761 | 0.3074 | 0.8982 |
| min pre-V2 legs 20 | 351 | 318 | -0.0093 | 0.2675 | -0.0348 |
| min pre-V2 legs 200 | 141 | 113 | 0.8748 | 0.4676 | 1.8707 |
| horizon 12 months | 247 | 181 | 0.2139 | 0.2770 | 0.7722 |
| horizon 36 months | 247 | 224 | 0.2592 | 0.3189 | 0.8128 |
| treatment: strict-leg forced share | 247 | 216 | 0.3895 | 0.2974 | 1.3099 |
| treatment: ETH-volume forced share | 247 | 216 | 0.1989 | 0.3375 | 0.5895 |
| treatment: forced-route SOURCE share only | 247 | 216 | 0.3685 | 0.5513 | 0.6686 |
| treatment: forced-route DESTINATION share only | 247 | 216 | 0.4995 | 0.5349 | 0.9339 |
| drop bottom decile of pool size | 222 | 191 | 0.5580 | 0.3258 | 1.7129 |
| drop the 5 largest exchanges by legs | 242 | 215 | 0.2801 | 0.3121 | 0.8974 |

### Falsification 1: the same design on a date when no mandate was removed

Pre-stated rule, fixed before the placebo was run. The placebo shifts the event to 2019-11-05, six months before V2, and truncates follow-up at six months so the whole outcome window closes on 2020-05-04 and cannot be contaminated by the event being falsified. The real event is re-estimated on the same six-month horizon so the two are comparable. The design PASSES only if the placebo coefficient is insignificant at 5% AND smaller in absolute value than the real six-month coefficient. It FAILS otherwise, including the case where the placebo is the larger of the two.

| design | n | exits | mean forced share | forced_share | robust se | t |
|---|---|---|---|---|---|---|
| real event, 6-month horizon | 247 | 124 | 0.1888 | 0.0311 | 0.2088 | 0.1491 |
| placebo event, 6-month horizon | 99 | 17 | 0.1120 | 0.0333 | 0.2736 | 0.1216 |

Placebo coefficient +0.0333 (t = +0.12), real six-month coefficient +0.0311 (t = +0.15). Insignificant placebo: True. Placebo smaller in absolute value than the real estimate: False. **Verdict: FAIL.**

The placebo carries 17 exits on 99 exchanges against 124 on 247 for the real event, because V1 in late 2019 was less than half the venue it was in May 2020, so the placebo is the weaker of the two designs and its standard error is larger (0.274 against 0.209). The two point estimates differ by 0.0021 log-months and both are within a quarter of a standard error of zero, so the pre-stated ordering condition is decided by noise. The rule was written for a design that finds an effect and it is uninformative against a null; it is reported as FAILED rather than rewritten, and falsification 2 is the check that has a pass criterion which means something when the estimate is zero.

### Falsification 2: a positive control on the design's own power

| true survival ratio, 95th vs 5th percentile of intensity | implied true coefficient | replications | share rejecting at 5% with the right sign |
|---|---|---|---|
| 0.900 | -0.201 | 1,000 | 0.092 |
| 0.750 | -0.549 | 1,000 | 0.422 |
| 0.500 | -1.322 | 1,000 | 0.984 |
| 0.250 | -2.643 | 1,000 | 1.000 |

Power against a halving of survival time across the intensity distribution: **98.4%**. Pre-stated threshold 80%. **Verdict: PASS.** So the estimate reported above is not small because 247 units cannot see anything: an effect that halved the lifetime of the most heavily routed exchanges relative to the least would have been detected in 98% of samples like this one, and it was not detected. The boundary of what this design can see is a survival ratio of about 0.64 across the same spread; power against a 25% shortening is only 42%, so effects in that range are genuinely out of reach and are not being claimed against.

### Power, stated as a number rather than as a null

With 247 exchanges the robust standard error on forced-route intensity in the primary specification is 0.307 log-months per unit of intensity, so the smallest effect this design would detect at 5% with 80% power is about 0.861 log-months per unit, which is 0.144 per standard deviation of intensity, a survival-time ratio of 0.87. Anything smaller than that is invisible here. The simulation above confirms the same number by resampling rather than by formula. Two qualifications keep this from being a clean precise null. The bound is on the PRE-SPECIFIED specification; the breadth-conditioned one has a wider interval whose lower end reaches a survival ratio of about 0.54 across the same spread, so a moderate effect is not excluded. And the bound is on a dose-response across exchanges, which is not the same quantity as the aggregate flow-type differential in section 2, so it should not be read as a direct test of that number's magnitude.
