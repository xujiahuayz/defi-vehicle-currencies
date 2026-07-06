# Model-to-Test Map

This note records the current small-model structure. The Mathematica sources are
`paper/vehicle_currency_model.wl` and `paper/vehicle_currency_numerics.wl`.

On the Studio machine, Wolfram 14.3 works with UCL's MathLM server. Wolfram 15.0
installs but the server does not grant licenses to that version. Run the model
with:

```bash
'/Applications/Wolfram 14.3.app/Contents/MacOS/WolframKernel' -script paper/vehicle_currency_numerics.wl
```

The script writes symbolic derivations and numerical figures to `output/model/`.

The empirical design is pinned in `paper/model_empirical_design.md`. That file is
the control document for the paper tests: it maps each model proposition to the
estimand, unit, empirical proxy, exhibit, and missing data/script inputs.

## Model

A trader swaps source token `i` into destination token `j`. The trader can use a
direct route `i -> j` or a vehicle route `i -> k -> j`. Route costs are the sum of
fees, settlement or credibility costs, and a reduced-form price-impact term that
falls with executable liquidity.

Vehicle-linked liquidity enters route costs, and empirically liquidity
concentration can predict future bridge use. The current empirical design treats
this as persistence/predictability, not as an identified causal LP feedback
channel.

## Propositions and Empirical Tests

**Proposition 1. Availability and thin-direct-market protection.** A token is
economically valuable as a vehicle when the vehicle route exists in endpoint
pairs where the direct route is missing or thin. Common-support cost advantage is
heterogeneous and is not assumed to hold in every deep direct market.

Empirical test: measure direct-route availability, vehicle-route availability,
no-direct/vehicle-available cases, thin-direct-market advantages, and
common-support cost heterogeneity by endpoint pair and trade-size bucket.

**Proposition 2. Liquidity concentration and bridge-use persistence.**
Vehicle-linked executable liquidity and LP concentration predict future bridge
share, but the current design does not identify causal liquidity feedback.

Empirical test: lag vehicle-linked liquidity and LP concentration; test whether
they predict future bridge share, route betweenness, or vehicle-route costs,
while presenting reverse causality and common shocks as unresolved.

**Proposition 3. Impact stress rotation.** A risk or credibility shock to the
incumbent vehicle lowers its route use relative to substitute vehicles within
common endpoint-pair opportunities on impact. The model is not intrinsically
daily, hourly, or weekly; the interval is an empirical implementation choice.

Empirical test: WETH bridge share falls with ETH downside stress and stablecoin
bridge share rises in the event window. In this dataset the robust window is
same-day; hourly, weekly, and multi-day windows are robustness checks that bound
the duration of the effect rather than part of the theoretical proposition.

**Proposition 4a. Direct-route opportunity expansion.** Increasing direct-pool
executable liquidity reduces no-direct/vehicle-available cases for affected
endpoint pairs. Broader V3 launch effects are suggestive unless a stronger
control group is added.

Empirical test: around V3 concentrated-liquidity adoption, focus on
no-direct/WETH-available cases and direct-route feasibility, with pretrend
diagnostics.

**Proposition 4b. Flash accounting.** V4-style netting separates route
intermediation from physical settlement: gross vehicle exposure can remain positive
while physical vehicle movement falls.

Empirical test: matched V3-V4 route units. Hold endpoint pair and intermediate
token fixed; compare ERC-20 transfer incidence, physical movement, and compression.
