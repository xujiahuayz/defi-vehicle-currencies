---
title: Live research and deliverable state
updated: 2026-08-18
target: Journal of Financial Economics
submission_ready: false
freeze_status: green
prose_node: tiered
meeting_edge: G/H baseline deliverables -> I iterative result-search loop
---

# Live workflow state

This file is the durable handoff for any executor. It reports current state; it
does not create a parallel workflow or certify files by identity.

Folder map:

- [`vehicle-transition.md`](vehicle-transition.md) records the primary transition
  evidence in detail.
- [`v1-forced-vehicle.md`](v1-forced-vehicle.md) records the mandate-removal case
  and its limits.
- [`venue-coverage.md`](venue-coverage.md) owns measured coverage bounds used in
  the paper appendix.

All other superseded or withheld finding memos were removed from the live tree;
their history remains in Git. The status below is the single current claim map.

```text
A question and setting                  DONE
  |
B literature and contribution          DONE for current paper
  |
C definitions and estimands            DONE
  |
  D raw data and reconstruction           STUDIO OWNER; M3 DELTA COVERAGE VERIFIED
  |
D3 purpose-built analysis inputs        READY ON BOTH HOSTS FOR ACTIVE CLAIMS
  |
E0 exploration                          DONE
  |
E1 confirmatory specification lock      DONE
  |
F registered confirmatory rebuilds      DONE; FINDINGS GATE GREEN
  |
G baseline JFE paper                    DONE; CLEAN 54-PAGE PDF
  |
H baseline presentation deck           DONE; CLEAN 46-PAGE PDF
  |
I parallel result-search loops          ACTIVE
  |                                     dominance drivers, LP behavior, framing
  |-- I1 propose mechanism and comparison set
  |-- I2 find/build eligible inputs
  |-- I3 run exploratory experiments
  |-- I4 triage against JFE bar
  |-- I5 integrate provisional result into paper/deck with status labels
  |-- I6 send review snapshot while I1-I5 continue
  |       weak or measurement-only  ---- back to I1/I2
  |       strong and defensible     ---- upgrade claim status and rebuild
  |
J rolling paper and deck                ALWAYS PRESENTABLE; REBUILT AS WORK MOVES
  |
P submission freeze                     NOT READY
```

## Executable claim set

`docs/specifications/confirmatory.json` has two execution-open claims:

1. `vehicle_transition`, the registered primary result.
2. `liquidity_capital_v2_predictability`, the registered mechanism result.

Both families have been rebuilt from their declared inputs after the lock, and
the executable findings gate is green. That is a reproducibility statement, not
a JFE submission decision. The live workflow is now at node I: parallel
result-search, draft-integration, and review loops. If the current evidence is
measurement-only or not economically interesting enough, the workflow keeps
looking while retaining a presentable paper and deck.

The loop targets the making of vehicle dominance (features, drivers, adoption,
reversal, persistence, and conditional choice) and liquidity-provision behavior
(capital stocks, liquidity-supply flows, provider entry/exit, reallocation, and
V3/V4 routing or netting behavior where inputs support it). A candidate result
can become headline evidence only after it states the unit, conditioning set,
economic magnitude, strongest rival explanation, literature contribution, and
complete producer-to-deliverable path. Provisional results may enter the paper
and deck only when explicitly labelled and reproducible enough for review.

The active provisional result stack now includes vehicle formation at market
birth, large-entrant stable routing, 30-day and 120-day birth-state persistence,
active-day birth-regime hysteresis, value-supported entry path dependence,
non-WETH entry-driver controls,
route-architecture entry interactions, stable turn-on in thin baseline markets,
rolling native-only-to-stable turn-on hazards, the direct-route by thinness
interaction, same-day and prior-30-day candidate-network reach inside observed mixed native-stable
risk-set checks, endpoint claim-class formation splits, endpoint price-history
formation screens, sticky incumbent
vehicle regimes, USDC/USDT concentration at stable-entry, stable-candidate
identity persistence, USDC/SVB stress-window identity persistence and LP capital
non-chase, extra-hop gas economics and route-level fixed-toll feasibility, the V2 liquidity
route-minus-capital gap, stable-basket portfolio rebalancing, delayed/asymmetric
LP rebalancing, LP stable-candidate response heterogeneity, venue-footprint and
pool-count extensive-margin behavior, V2 pool-capital concentration and
fragmentation, plus same-pool LP capital-chase rival screens, bounded V3
fee/rent-incidence and TVL-normalized fee-yield screens, V3 mint/burn action-count and provider-day responses, and local
bridge-liquidity dominance plus stable-specific dynamic local bridge-depth
feedback. The deck
also carries the traditional-FX route analogy as motivation. These layers
strengthen the
mechanism story but do not change the registered confirmatory claim set.

Routing maturation, full same-state direct-cost dominance, the joint V2/V3
capital-flow family, provider-flow measurement, and V4
settlement/netting claims are blocked, withheld, supporting, or outside the
executable perimeter until they receive a complete
producer-to-deliverable path. They must not be presented as established findings.

## Current blockers

There is no repository or data-handoff blocker. Studio is the canonical raw-data
owner and retains the larger corpus; M3 intentionally retains a smaller
review/build subset. Studio has no LaTeX toolchain, so the clean compile and
visual gates run on M3 and the built PDFs travel through Git. The open work is
scientific expansion and revision toward the JFE bar.

The executable check is:

```bash
./scripts/run scripts/verify/audit_findings_freeze.py
```

It checks declared paths and whether every active output is newer than its inputs
and the lock.

## Data consolidation state

- M3 has 119,258 regular raw files totaling 92,872,183,217 bytes (86.494 GiB),
  with no raw symlinks. It is the TeX/build and review host, not the canonical raw
  store.
- Studio has 714,871 regular raw files totaling 169,525,329,199 bytes
  (157.883 GiB), with no raw symlinks. The comparison found 4,473 M3 paths absent
  initially: 1,911 records already had a Studio copy under the same
  source/date-bearing basename and byte size, and all 2,562 genuinely new files
  were copied to their exact relative paths with zero missing or size mismatches.
- The 4,686 M3 processed/unified files were compared by path and size with
  Studio's 12,864-file derived boundary. Six absent current support inputs were
  copied; differing Studio files were retained rather than overwritten.
- Stale runtime caches and derived artifacts were removed from both checkouts
  (recoverable copies are in each machine's Trash).
  Raw RPC cache records were moved into `data/raw/ethereum/rpc_cache/` before the
  runtime cleanup. Cross-machine raw equality is intentionally not claimed:
  Studio is the owner and M3's smaller copy is a working/build subset.

## Definition guards

- Vehicle status is binary; vehicle dominance is continuous.
- Cost domination is a distinct object and is not called vehicle dominance.
- The primary transition result is descriptive unless the registered design earns
  stronger identification.
- Predictive capital associations are not causal feedback.
- A blocked or withheld family never enters the abstract, headline table, or deck
  as an established result.
- Every quantitative paper/deck object must trace through a script to processed
  data and retained raw evidence.

## Deliverable state

The current branch compiles a 54-page paper and a 46-page deck after the
provisional mechanism reruns. The paper and deck compile with zero undefined
references. The repository passes 704 pytest tests, the findings gate, and every
blocking conformance check. There is one manuscript under `paper/` and one
presentation under `deck/`; Git history is the archive.

These are rolling deliverables, not final submission deliverables. The paper and
deck remain presentable throughout the research process. Before submission
freeze, they still need JFE-level triage of economic magnitude, literature
positioning, and equation/structure depth. A weak candidate loops back to more
search rather than entering the headline evidence.
