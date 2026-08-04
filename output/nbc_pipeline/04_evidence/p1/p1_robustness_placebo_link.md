# P1 robustness check: falsification/placebo (LINK, non-candidate token)

LINK (Chainlink) is a liquid, actively-traded Ethereum ERC-20 with real Uniswap V3 pools and real presence as an intermediate hop in some routes, but it is explicitly NOT in this repo's 5-token vehicle-candidate set. Its own L (log_link_liquidity, from V3 pool TVL where LINK is a pool side, same MAX_POOL_TVL_USD filter as the real candidates) and S (link_bridge_share, same route-decomposition methodology as bridge_share) were built by scripts/build_link_placebo_panel.py. No placebo D was built -- see that script's docstring for why (would require a full multi-year on-chain V2+V3 quote-simulation rebuild, out of scope for this pass). Because there is only one placebo unit, no token+date two-way FE is possible (date FE would perfectly absorb all its own variation with a single cross-sectional unit); instead this is a single-series time-series regression of the same forward change on the same regressor, with month dummies (not date FE) absorbing trend/seasonality and Newey-West HAC SEs (lag=max(tau,5)) in place of Driscoll-Kraay (which requires cross-sectional replication at each date). This is consequently a different (necessarily weaker) estimator than the pooled headline, so 'same sign, lower significance' is not itself evidence either way -- what matters is whether the LINK coefficient is comparable in sign AND economic magnitude to the pooled headline coefficient.

## Results
| Equation | Horizon (days) | N (LINK own-series) | Beta (LINK) | SE (Newey-West, LINK) | p (Newey-West, LINK) | Beta (5-candidate pooled headline) | p (Driscoll-Kraay, headline) | Same sign as headline? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S_on_L | 1 | 1882 | 0.0003 | 0.0004 | 0.380 | 0.0223 | <0.001 | yes |
| S_on_L | 7 | 1876 | 0.0001 | 0.0005 | 0.911 | 0.0261 | <0.001 | yes |
| S_on_L | 14 | 1869 | -0.0008 | 0.0006 | 0.183 | 0.0270 | <0.001 | no |
| S_on_L | 30 | 1853 | 0.0001 | 0.0005 | 0.898 | 0.0270 | <0.001 | yes |
| L_on_S | 1 | 1882 | -0.6536 | 0.4557 | 0.152 | 0.0189 | 0.046 | no |
| L_on_S | 7 | 1876 | -2.4480 | 1.1677 | 0.036 | 0.0377 | 0.010 | no |
| L_on_S | 14 | 1869 | -1.4347 | 1.5771 | 0.363 | 0.0483 | 0.051 | no |
| L_on_S | 30 | 1853 | 0.1612 | 1.2871 | 0.900 | 0.0842 | 0.014 | yes |

