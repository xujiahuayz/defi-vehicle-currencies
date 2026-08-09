# Node I, round 1: adversarial review and approval gate

Node I output, 2026-08-06. Standard applied: published papers in the *Journal of Financial Economics*. Where a venue norm is claimed below, the paper is named and the observation is one I made in the file in `literature/papers/` or its extract in `literature/text/`, not a recollection.

Scope: `docs/finding-native-intermediation-advantage.md` as the headline under review, with `docs/research-workflow.md` sections 3, 4.0, 4.1 and 7, `docs/paper-spine.md` and `docs/deck-outline.md` read for whether the requirement itself is sound. Java lifted the manual execution hold and delegated approval to this review. This review withholds approval.

## 1. Verdict

**APPROVAL WITHHELD. The estimate may not be cited, and the five-venue rebuild is not the thing that would earn approval.**

**A JFE editor would desk-reject this as framed.** Four grounds, in the order an editor would reach them.

First, the reported quantity is not a cost. The headline is a shift in the probability that one quoted number exceeds another, evaluated at a threshold the design absorbs. In Makarov and Schoar (JFE 135, 2020, pages 293 to 319) the reported quantities are the price deviation in percent and the money left on the table in dollars, stated in the introduction as daily potential arbitrage profits often above $75 million and a minimum of $2 billion cumulative from December 2017 to February 2018. That is what an editor recognises as a magnitude. A 38.3 percentage-point movement in a dominance indicator is a statement about a cumulative distribution function evaluated at one point, and the mapping from that shift to basis points depends on the density at the threshold, which the document does not report. This repository owns the continuous object. `docs/paper-spine.md` Table 5 already prints median cost gaps in basis points, and the registry in `src/ddvc/variable_registry.py` carries the cost components. Reporting the binarised version of a variable you measured continuously reads to an editor as the specification that produced the largest number.

Second, the framing states the maintained assumption of the literature it cites. Krugman (Journal of Money, Credit and Banking 12(3), 1980, pages 513 to 526) opens on the observation that one national currency has held the international-money role over most of the past hundred years and builds the vehicle role on the currency with the lowest transaction costs in the exchange structure. `docs/research-workflow.md` section 3 then defines the native platform asset as the asset with the "thickest incumbent pairing network". A finding that the asset defined by having the thickest network is the cheapest one to route through does not survive an editor asking what was learned.

Third, the paper as spined has no mechanism. `docs/paper-spine.md` section 2.5 records that every claim in section 5 is PENDING, and section 1.3 makes section 5 the section carrying the mechanism weight because the lead result is a description. `docs/research-workflow.md` section 1 records that 6 of 9 empirical exemplars make no causal claim and substitute a data moat plus a validation apparatus, and section 2 retracts the data-moat reading for this project. A submission with a descriptive lead result, an empty horse race, and no data moat has nothing in the position where JFE empirical papers put their contribution.

Fourth, the internal arithmetic does not hold, and an editor sees it inside one page. Line 13 of the finding document reports the coefficient -0.3834 with standard error 0.0372 on "177,106 identifying fixed effects and 11,248,255 routes". The robustness table on lines 25 to 33 assigns -0.3834, 0.0372 and 11,248,255 to the 7-day window, where the identifying fixed-effect count is 45,630, and assigns 177,106 to the 1-day window, where the coefficient is -0.3837 and the row count is 11,045,551. The headline sentence pairs one specification's estimate with another specification's identifying count. `docs/paper-spine.md` Table 6 column 5 has it right at 45,630, which means the two live documents disagree about what the headline specification is.

## 2. Ranked objections

Ranked by probability of killing the paper, with the blast radius of each stated because that is what the ordering turns on.

| # | Objection | What it kills | Fixable by the five-venue rebuild |
|---|---|---|---|
| 1 | Same-state route-cost gaps of the reported size are atomically capturable at zero capital risk, so they are not costs a trader faced | The whole route-cost panel, sections 4 and 5.1 of the spine, slides 11 to 13 | No |
| 2 | The size gradient carrying the non-mechanicalness defence is not distinguishable from zero, t about 1.5 | The claim to be a finding at all, and the hinge of spine section 5.2 | No |
| 3 | The panel is the 200 most heavily bridged pairs per day, so groups enter on the intensity of the behaviour being explained | Identification of the level | No |
| 4 | The estimate is constant in calendar time while the lead result is a six-year migration, and spine 5.1 concedes a constant advantage cannot produce one | The coherence of the paper, and the verdict in Table 8 row 1 | No |
| 5 | The defence against quote collapse conditions on a monotone function of the dependent variable | The project's only current answer to threat 1 | No |
| 6 | Candidate balance within group is not what the identification argument asserts, and gas enters as a constant the fixed effect absorbs | The interpretation of the level and of the size profile | Partly |

### Objection 1: the reported gaps are not costs, because nothing stops them being taken

This is the objection that ends the submission, and it has the widest blast radius because it attacks the panel and not the specification.

`docs/paper-spine.md` Table 5 Panel A reports, for native-intermediated routes, a median cost gap gross of gas of -2,459 basis points, against -492 for stable and -123 for imported. A median absolute gap of 24.6% between a direct pool and a two-leg route for the same ordered pair at the same reconstructed pre-trade state is not an execution cost. The finding document's own screen table says the same thing on the multi-venue panel: restricting to routes whose absolute advantage is at most 50% keeps 8,072,791 of 11,248,255 rows, so 28.2% of the estimation sample carries a same-state discrepancy above 50%, and restricting to at most 5% keeps 6,015,748, so 46.5% carries a discrepancy above 5%.

Makarov and Schoar is the paper that establishes what a defensible number looks like here, and it establishes the opposite. They report that price deviations between exchanges in the same country "typically do not exceed 1%, on average", that the average within-region arbitrage index for the four major US exchanges runs below 2% price dispersion, and that the ethereum-to-bitcoin spread was 3% during the same period when dollar-to-bitcoin between the US and Korea exceeded 20%. Their large numbers, the 15% daily average and the 40% peak of the Korean premium, are the ones they spend an entire top-level section defending. Section 8, "Discussion of arbitrages and constraints", opens by conceding that the textbook arbitrage "is not possible", and then names the frictions that sustain the gap: roughly an hour for a bitcoin transaction to register, several hours to several days for fiat transfer, and the absence of short selling on the Korean and Japanese exchanges that traded 10 to 25% above the rest.

**Evidence correction, 2026-08-09.** The original review overstated this objection. A direct pool and a two-leg route on the same chain can be joined atomically, which removes unmatched-leg risk but not financing, gas, competition, reversion, state latency or builder costs. The repository's 79-day round-trip distribution establishes a large self-returning population, not that every closed route is arbitrage or wash trading and not continuous capture capacity. The objection survives in bounded form: a 2,459-basis-point same-state gap is implausible unless it clears measured execution frictions, so transaction-state support and the quantitative arbitrage bound are required. The withdrawn flash-loan, zero-capital and exhaustive round-trip-classification statements must not be cited.

So the referee's question is not whether the coefficient is estimated correctly. It is what the quoter returns off the support of executed trades. The validation on record is 1,550 of 1,655 swaps within 1% with a median absolute error of 0.00 basis points, measured on swaps that happened, on the single-venue two-hop quoter. The panel's job is to price 123.8 million routes that did not happen, and the error distribution out there is unmeasured. The gaps above have exactly the shape of extrapolation error in pools with stale or thin state, and quote collapse is its visible tail. Curve integration removes one cause of that error. It does not measure the error.

**What discharges it.** An executability screen and an error bound off-support, reported as a top-level section. Take realised two-leg routes, price the direct alternative at the same state, and report the distribution of the gap; any mass beyond a few hundred basis points is either arbitrage that was taken or measurement error, and the split is testable by checking whether an atomic cycle appears in the same block. Then re-estimate on the arbitrage-consistent subsample and report what the coefficient does. If the coefficient survives on gaps under 200 basis points with the sample selected on something other than the dependent variable, the paper has a result. If it does not, the finding was the error distribution.

### Objection 2: the size gradient is not there

This is the objection that removes the paper's claim to have found anything, and it is arithmetic on the table in the document under review.

The non-mechanicalness screen turns on one contrast: -0.4115 at $1,000 with standard error 0.0328, -0.4113 at $10,000 with 0.0390, and -0.3218 at $100,000 with 0.0437. The first two differ by 0.0002, which is a two-hundredth of a standard error across a tenfold change in notional, so the profile is flat over the range where the document says a depth mechanism should already be moving. The whole gradient is the single step from $10,000 to $100,000, a difference of 0.0895 against a standard error of the difference of 0.0586 if the subsamples were independent, giving t = 1.53 and p about 0.13. Across the full range the difference is 0.0897 with t = 1.64 and p about 0.10. The subsamples are drawn from one panel and share clusters, so the naive standard error is the optimistic case and no interaction test exists anywhere in the repository.

The document states its own minimum detectable effect at 0.104. The size gradient it is being asked to detect is 0.090. The design cannot see the gradient at conventional power, by the document's own power calculation, and reports it anyway as the feature that makes the result non-mechanical.

This is not a small correction. `docs/finding-native-intermediation-advantage.md` line 66 uses the profile as the reason the result "is not mechanically true". `docs/paper-spine.md` section 5.2 calls it "the hinge on which this section now turns" and lists it as one of the two predictions supporting the strongest account in the horse race. Table 8 row 2 records "native advantage falling in $q$" as EXISTS. `docs/deck-outline.md` slide 12 already carries the size story into a visual whose stated read is "the signature of a fixed cost". A gradient with t = 1.5 is load-bearing in four places.

Threat 4 on the brief's list, the advantage weakening with size being the opposite of what depth predicts, is therefore not a threat. It is a non-result being carried as a finding. The puzzle dissolves and takes the defence against tautology with it.

**What discharges it.** One pooled specification with the native indicator interacted with log notional, clustered as the headline is, on a notional grid finer than three points, with the interaction coefficient and its standard error reported. Spine 5.2 already names the finer grid as needed. Until that runs, no document may describe the advantage as weakening with size.

### Objection 3: the sample is selected on the behaviour being explained

`docs/deck-outline.md` A14 states the panel construction: "200 most heavily bridged ordered pairs per day", five vehicle candidates, three notionals, 24 hourly states.

Pairs enter the panel on days when they are most heavily bridged, meaning on days when intermediated routing through a vehicle is most intense for them. Intensity of vehicle routing is jointly determined with the vehicle route being cheap, which is the quantity being estimated. Selection operates at the pair-day level, which is the level of the absorbed group, so pair-window fixed effects cannot undo it. Conditioning on inclusion shifts the joint distribution of candidate-specific leg depth within the surviving groups, and it shifts it toward whichever candidate did the bridging that got the pair selected. Across 2020 to 2026 that candidate is predominantly the native asset, by the project's own transition series, which puts the native share of intermediated value at 73.0% at the start of the sample.

The direction of the bias is toward the reported sign. This is a group-level selection problem of the kind a group fixed effect is powerless against, and a referee who reads A14 before Table 6 will raise it first.

**What discharges it.** Redraw the panel on pairs sampled on something orthogonal to intermediation intensity, such as all pairs with a live direct pool above a size floor, or a volume-stratified draw, and report the coefficient on both draws. If the two agree, say so in the data section. If they do not, the selected draw is the finding.

### Objection 4: the estimate has no time dimension, and the paper is about time

`docs/paper-spine.md` section 5.1 states the problem in its own words: "a mechanism that favours the native asset throughout the sample cannot by itself produce a role moving away from it". The lead result of the paper, per section 1.3 and section 2.3, is that the intermediation role migrated from the native asset to the stable numéraire, native value share falling from 73.0% to 14.8% while stable rose from 21.2% to 50.1%.

The headline coefficient is pooled over 2,238 days and contains no time interaction. Not one specification in the finding document splits by year, era or side of the crossover. The robustness table varies the absorbed window from 1 day to 120 days and reports that the coefficient moves 0.0022, six hundredths of a standard error, across a 120-fold change. The document presents that as evidence the window does not drive the answer. It is also the symptom: an estimate that is invariant to the width of the time window it absorbs is a cross-sectional average with the time variation integrated out, and time variation is the dimension the paper's lead result lives in.

The consequence is that Table 8 row 1 is incoherent as written. It records the thick-market account as "Supported on the level" using this coefficient, in a table whose leading fact is the role moving away from the asset the coefficient favours. Either the native advantage declines across the sample, in which case the trend is the headline and the pooled level is the wrong statistic to report, or it does not, in which case account 5.1 is refuted by the paper's own estimate and should be reported that way under the standing rule that a null belongs in results. Both readings are publishable. The pooled number is neither.

**What discharges it.** The same regression with the native indicator interacted with year, or estimated by era on both sides of the 2022-Q1 value crossover, with the point estimates plotted. This is one line of code against a panel that already exists, and it is the highest-value hour of work available to node F.

### Objection 5: the defence against collapse conditions on the dependent variable

The finding document's answer to the collapse threat appears twice, on line 64 and line 82: restricting to routes where the direct route's advantage is within 5% either way "excludes collapsed quotes by construction" and leaves the coefficient at -0.3986.

The outcome is `dominated`, an indicator for the direct quote exceeding the vehicle quote. The advantage is the signed continuous version of the same comparison, so `dominated` is one exactly when the advantage is positive. Restricting to absolute advantage at most 5% keeps observations where the latent index generating the outcome is near its threshold and drops observations where the outcome is determined with certainty. That is selection on a monotone function of the dependent variable. In a linear model on a binary outcome it changes the estimand, and the direction depends on the shape of the latent error distribution for each candidate type, which is precisely the thing that differs by candidate and is precisely what the collapse diagnostic says is wrong.

So the coefficient of -0.3986 on the trimmed sample is not a robustness result. It cannot discharge the collapse threat because it operates on the same variable the threat is about, and it is not interpretable as an estimate of the original parameter. The project's only current defence against its own most serious diagnostic is void.

Compounding this, the collapse diagnostic itself rests on 975 native, 5,253 stable and 924 imported quotes, which is 7,152 observations, or 0.064% of the 11,248,255-row estimation sample. Both the alarm that stopped the estimate and the plan that is supposed to clear it rest on six ten-thousandths of the data, on an object the document does not define. A referee will ask what a "quote" is in that table and why the answer differs from a route.

### Objection 6: candidates are not balanced, and the gas term cannot help

The identification argument on line 19 of the finding document is that "the counterfactual panel prices the route through every vehicle candidate for every pair-window, so a group contains all candidates by construction". The collapse table on lines 74 to 78 contradicts it. Native carries 975 quotes and imported 924, a ratio of 0.95, which is consistent with balance. Stable carries 5,253, which is 5.39 times native. With five candidates and three stable proxies the expected ratio is 3.0. The observed excess of 1.8 times is unexplained, and under the by-construction claim it should not exist at all.

If candidates are not balanced within group, the fixed effect does not do what the document says, and the coefficient partly measures which candidates were quotable. That is the graded version of the collapse threat and it is not confined to the tail. A vehicle whose two legs are quotable on more venues than a rival's has its route quote formed as a maximum over more draws, so it wins on order statistics with equal true depth. Native legs against WETH are quotable on more venues than stable legs at every point before Curve enters, and the trim in objection 5 does nothing about it because it acts only on the extremes.

Gas cannot rescue the size profile either. `docs/deck-outline.md` A7 and slide 11 specify the gas model as a single figure of 74,096 units for the extra hop, applied by route topology. A cost that is identical for every candidate in a group is absorbed by the group fixed effect and cannot move the coefficient at all. The finding document's line 88 nonetheless argues that adding all-in cost "should sharpen the size profile" and not reverse it, "since gas hits small trades hardest and the advantage is already largest there". That reasoning has no channel: what hits all candidates equally within a group is invisible to this estimator. The only channel is the cross-candidate gas differential, and that is the one quantity nobody has measured. It is not small. A Curve stableswap leg and a tick-crossing concentrated-liquidity leg do not cost the same gas as a constant-product leg, and A8 reports the extra hop at 478 basis points of a $100 notional, so differentials in the tens of thousands of gas units land in the tens of basis points at retail size, against a signal the workflow describes as tens of basis points. This has a direction: Curve legs are the gas-expensive ones, so a five-venue rebuild that is gross of gas will overstate how much of the native advantage Curve explains.

## 3. The four known threats, assessed

**Threat 1, quote collapse, is not fatal on its own and is being mis-diagnosed.** The one-for-one tracking of the 28.6-point dominance gap against the 28.0-point collapse gap is suggestive, and the attribution to missing venues is plausible. It is not established, because the diagnostic runs on 7,152 undefined units and the defence against it is void per objection 5. Collapse is the visible tail of the off-support quoting error in objection 1, and treating it as a venue-coverage problem will produce a rebuild that removes the tail and leaves the body.

**Threat 2, the missing Curve venue, is a real defect and the least dangerous of the four.** It is a coverage gap with a signed direction already stated in `docs/research-workflow.md` section 3, it is now fixed at 0.022% median error, and a rebuild answers it. It is also the only one of the four the rebuild answers. The risk is that the rebuild is treated as clearing the headline. It clears one of six objections above, partly.

**Threat 3, cross-venue state misalignment, is fatal as executed and unresolved as fixed.** A median 0.345% price gap against a signal of tens of basis points means the earlier estimate carried a state error five to ten times its own signal, which is enough that the earlier number should be regarded as uninformative and not as an estimate with a bias to be corrected. Moving from end of day against end of hour to per-hour state does not clear it. The panel runs at roughly 215,000 swap legs per day, so an hourly snapshot is stale by thousands of legs, and staleness is worst in the most actively traded pools, which are the native ones. The workflow's own measurement in section 4.0 is that intraday price movement swamps execution cost by a factor of 34, with a median absolute gap of 775 basis points on volatile pairs. Section 4.2 already requires transaction-time state and requires the wedge to be reported wherever daily state is used. Per-hour state does not satisfy that requirement; it narrows the violation. Nothing in the repository reports the hour-to-block wedge.

**Threat 4 is not a threat.** Per objection 2 there is no size gradient at conventional power. This one should be struck from the list of concerns and added to the list of claims to withdraw.

**None of the four is individually fatal in the way objections 1 and 2 are.** Threat 3 comes closest, and it is fatal to the estimate on record while being silent on the rebuild.

## 4. Is the research question right?

**No, and this is the most valuable thing in this review.**

The counterfactual is a capability, and the project is spending it on the wrong estimand. `docs/research-workflow.md` section 3 gets the capability exactly right: the quote for the route nobody took is never observed in FX, and on-chain it can be reconstructed and priced. Section 4.0 then names what that capability is for, in the sentence that should be the paper's abstract: "the FX literature's decisive gap is that an incumbent's cost advantage is itself a consequence of its incumbency, so the data never contain the state in which a currency holds the vehicle role while being strictly cost-dominated by a rival."

The project has already found that state, and it is common. 17.9% of intermediated routes are dominated gross of gas and 30.0% all-in, on 103,857 routes. That is the fact no FX paper can produce, and it is sitting in `docs/finding-cost-dominance-measured.md` supporting a slide about marginal frequency.

The question the same data answers, and which the headline is at best a first-stage check for, is how long the role survives once it is cost-dominated. Stated as a paper: an incumbent intermediary keeps the role for some period after it stops being the cheapest route, the length of that period is measurable in days on-chain and is unmeasurable in FX, and the money left on the table over it is a number in dollars. Add the asymmetry test that spine Table 7 Panel B already specifies, whether a displaced incumbent needs a larger cost edge to return than the challenger needed to win, and the paper separates hysteresis from persistence, which is the question Krugman's multiple-equilibrium structure raises and cannot settle with FX data. Flandreau and Jobst rejecting strong lock-in while confirming persistence, flagged in workflow 4.3 as abstract-verified only, is the closest prior claim and the thing this design would beat on its own terms.

That question has what the current one lacks. It has a time dimension, so it speaks to the lead result instead of contradicting it. It has an outcome in economic units, dollars foregone and days of delay, which is the Makarov and Schoar move and what an editor recognises. It has an asymmetry test that no tautology delivers. It cannot be restated as a definition, because nothing in the definition of a thick-network incumbent says how fast a role moves when the network stops paying.

The second-best question is incidence, and it is the one the size profile was reaching for: who pays for the incumbent's centrality, and whether the burden falls on retail-sized trades. That question is currently unavailable, because per objection 2 the size gradient is not measured.

**Reject the requirement, not only the execution.** The route-cost panel was specified to answer "is the native route cheaper", and it answers that question well enough to show the question is not worth the instrument. The instrument's comparative advantage is over time and at the moment of displacement. Spend it there. The level comparison becomes a validation exhibit in section 2 and stops being a result.

## 5. Is the finding a finding?

**No. It is close enough to a definition that a referee will say so in one sentence, and the piece meant to rescue it does not hold.**

Consider what the estimator can see. Within a pair, window and notional, the direct quote is common to every candidate at each hour, so it enters only as a threshold. The variation the coefficient uses is entirely across candidates, and the coefficient is therefore a statement about the relative output of native two-leg paths against non-native two-leg paths. It contains no information about direct pools. The headline sentence, "a direct pool is 38.3 percentage points less likely to beat a native-intermediated route", describes a comparison the design does not make, and the finding document's own title, that the native asset is a better intermediary, is the accurate reading of the same number.

That accurate reading is a depth ranking of WETH pools against USDC pools. `docs/research-workflow.md` section 3 defines the native platform asset as the one with the thickest pairing network. The measured object and the defining property are the same object, and the estimate recovers the definition with a standard error.

Four things could have made it a finding, and each is absent. A magnitude in economic units would have, because "the native route is cheaper by X basis points at a $10,000 notional" is a quantity nobody has and the definition does not supply; the binary outcome discards it. A time profile would have, because a declining advantage against a migrating role is a mechanism test; the pooled design integrates it out. A size profile would have, because incidence is not implied by depth; it is not measured at conventional power. A comparison holding the number of quotable pools fixed across candidates would have, because winning a maximum over more draws is not the same property as being deep; nothing in the repository holds it fixed.

The document's non-mechanicalness screen also passes on the wrong test. It asks whether the coefficient survives dropping thin candidates and trimming extremes, and it survives both. Neither addresses mechanicalness. A result is mechanical when its sign follows from the construction, and dropping the imported asset does not change the fact that the native asset was defined as the one with the deepest network. The screen the workflow specified in section 4 is the right screen; what was run does not implement it.

## 6. Spine and deck: what would embarrass the author

Ordered by how badly it would land.

**The spine cites a number its source forbids citing.** `docs/paper-spine.md` section 2.4 records the native coefficient with status EXISTS and the claim that quoting every candidate "settles the sign", and section 5.1 says "Commit 0a4da17 settles the level". `docs/finding-native-intermediation-advantage.md` opens with a bolded "Do not cite this estimate." Two tracked live documents disagree about whether the paper's most important number may be used, which is the failure mode the standing rule in workflow section 0 about superseding was written to prevent, arriving in a new form.

**A section of the paper spine cites a git commit hash as its evidentiary authority.** Section 5.1's status line reads "Commit 0a4da17 settles the level". If any part of that sentence reaches a draft it is internal process in the deliverable, banned by workflow section 0, and it is the same class of error as the abstract-reconciliation slide that survived three review phases.

**Slide 11 advertises a gas term the headline does not contain.** `docs/deck-outline.md` slide 11 lists "Gas added per route topology from receipts" and its visual specifies a dashed arrow labelled "add 74,096 units" joining the vehicle lane only, with the read that "the gas asymmetry attaches to exactly one lane". The coefficient on slide 13 is gross of gas. A speaker who presents the design and then the result has claimed a cost term the number omits, and the first question from the floor is what happens when gas goes in.

**A9 defends the wrong exclusion.** "Why gas is not a control" argues correctly that a variable on the causal path cannot be netted out by including it. The live issue is that gas is absent from the outcome, and declining to condition on a mediator is a different act from declining to measure what the trader pays. Sitting two slides after A8, which prints the extra hop at 478 basis points of a $100 notional, A9 reads as a rationalisation. The workflow's own citation at 4.2 is Barbon and Ranaldo, whose headline is that validator gas dominates trader cost ahead of classical price impact. Citing that paper for the cost definition while presenting a cost measure without gas is the exposure.

**Slide 12's spoken caveat is broken by the finding document's title.** The caveat the speaker states aloud is that the marginal frequency "does not license a claim about which asset type is the better intermediary". The finding document is titled "The native platform asset is a substantially better intermediary". Under questioning the speaker has to hold both.

**Table 6 puts a sign flip in one row and labels the preferred column as the one the paper needs.** Columns (4) and (5) of the native-type indicator read +0.094 (0.269) and -0.383 (0.000), and the note calls column (5) "the specification the paper needs and the single most valuable thing node F can deliver". A referee reads "needs" as the author naming the wanted answer, in a row that already flipped sign once. The two columns rest on different samples with no test that they are comparable.

**Three numbers exist in this repository for the same qualitative gap.** Table 5 Panel A gives native 13.2% dominated against stable 16.8%, a gap of 3.6 percentage points. The collapse table gives 58.1% against 86.7%, a gap of 28.6. Table 6 column 5 gives 38.3. Different samples and different conditioning explain part of it and no document explains any of it.

**Table 5 Panel A prints a median execution-cost gap of -2,459 basis points.** In a table of execution costs, that number invites the reader to conclude the quoter is wrong before reaching Panel B.

**Spine 2.4 asserts three size relationships in adjacent rows.** Dominance rising from 17.0% to 39.1% across the $100 to $1,000 bin all-in, log notional at -0.042 within pair-day, and the native advantage falling from -0.4115 to -0.3218, sit as three separate EXISTS rows with no reconciling sentence. They are not all about the same conditioning, and nothing on the page says so.

**A16 discloses an outcome-correlated filter and stops.** "Notional band removes 36.9% of pair-days and correlates with the outcome." Disclosed and unbounded is worse than undisclosed, because it establishes that the authors knew and shows what they did about it.

**A11 reports a past bug in the authors' own classification.** "Native ETH at the zero address was once misfiled, 19.8% of the residual in 2026 samples." The corrected coverage belongs on the slide. The history of the mistake is internal process.

## 7. Requirements I reject

**Reject: "no standalone identification, empirical-strategy or robustness section" as applied to this paper.** Spine 1.2 records 0 of 7 papers with data having one and 0 of 9 having a robustness section, and derives the rule that a defence travels with the claim. The rule is well measured and wrong here. Makarov and Schoar, one of the seven JFE papers the spine itself counted, give a whole top-level section 8 to "Discussion of arbitrages and constraints", whose entire content is why their measured price deviations are real given latency, short-sale constraints and capital controls. That is a standalone defence of the measurement, sitting in a JFE paper, and it is the section this paper most needs and the architecture forbids. What generalises from the exemplars is that a defence of a *result* travels with the result. A defence of the *object being measured* gets its own section, and this paper's object is a counterfactual quote that nobody executed. Adding section 2.5 or a top-level section on executability is not a violation of the invariant. It is the invariant read correctly.

**Reject: the eight-table, four-figure target as a design constraint at this stage.** Spine 1.2 calibrates it from the read sample and section 3 then carries eight table shells in which the majority of cells read PENDING. Table shells with PENDING cells are a plan presented as an architecture, and Table 8, "the table the paper is organised around", has every estimate cell empty. The count is an output of having results. Using it as an input has produced a spine that looks finished and is not, which is what let the headline pass into two documents as EXISTS.

**Endorse and tighten: workflow 4.2's requirement that gas per hop be measured from receipts and that omitting gas biases the panel toward the vehicle route.** That requirement is correct and the headline violates it. Tighten it: a per-hop constant does not satisfy it, because a constant common to candidates is absorbed. The requirement is a *candidate-specific and venue-specific* gas term.

## 8. What would change the verdict

The five-venue rebuild is not on this list, because it addresses one objection out of six.

1. An off-support quoting-error bound, and an executability screen, reported as a section. Objection 1.
2. The native indicator interacted with log notional on a finer grid, with the interaction standard error. Objection 2.
3. The same coefficient by year or by era across the 2022-Q1 crossover. Objection 4.
4. The panel redrawn on pairs selected orthogonally to bridging intensity. Objection 3.
5. A candidate balance table by group, replacing the by-construction claim with a count. Objection 6.
6. The headline restated in basis points and in dollars foregone, with the binary retained as a secondary exhibit. Ground 1 of the desk-reject.
7. Line 13 of the finding document corrected so its identifying count matches its coefficient, and spine 2.4 and 5.1 marked to match the source's provisional status. Ground 4.

Items 2, 3 and 5 run against the panel that already exists and are hours of work. Items 1, 4 and 6 are the ones that decide whether there is a paper.

**Recommended disposition.** Withhold approval on the headline. Hold the five-venue rebuild to a validation exhibit and not to a re-run of the same estimate, because re-running it produces a second uncitable number. Reopen the question per section 4 of this review before node F spends another cycle on the level.
