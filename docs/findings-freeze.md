---
title: Live research and deliverable state
updated: 2026-08-18
target: Journal of Financial Economics
submission_ready: false
freeze_status: green
prose_node: tiered
meeting_edge: G/H deliverables -> cross-host sync and handoff
---

# Live workflow state

This file is the durable handoff for any executor. It reports current state; it
does not create a parallel workflow or certify files by identity.

```text
A question and setting                  DONE
  |
B literature and contribution          DONE for current paper
  |
C definitions and estimands            DONE
  |
D raw data and reconstruction           CURRENT-REPO OWNERSHIP DONE; RAW MIRROR IN PROGRESS
  |
D3 purpose-built analysis inputs        READY ON BOTH HOSTS FOR ACTIVE CLAIMS
  |
E0 exploration                          DONE
  |
E1 confirmatory specification lock      DONE
  |
F registered confirmatory rebuilds      DONE; FINDINGS GATE GREEN
  |
G JFE paper                             DONE LOCALLY; CLEAN 47-PAGE PDF
  |
H presentation deck                    DONE LOCALLY; CLEAN 37-PAGE PDF
  |
P submission freeze                    PENDING FINAL TEST, SYNC, COMMIT, AND PUSH
```

## Executable claim set

`docs/specification-lock.json` has two execution-open claims:

1. `vehicle_transition`, the registered primary result.
2. `liquidity_capital_v2_predictability`, the registered mechanism result.

Both families have been rebuilt from their declared inputs after the lock, and
the executable findings gate is green. Routing maturation, direct-cost dominance,
the joint V2/V3 capital-flow family, rent incidence, and persistence/hysteresis are blocked,
withheld, supporting, or outside the executable perimeter. They do not hold the
working paper and deck hostage and must not be presented as established findings.

## Current blockers

- Finish the full raw mirror between M3 and Studio in the background; the active
  three-input claim perimeter is already present on both hosts.
- Complete the final test/build check, commit and push `main`, then fast-forward
  the clean Studio checkout.

The executable check is:

```bash
./scripts/run scripts/audit_findings_freeze.py
```

It checks declared paths and whether every active output is newer than its inputs
and the lock. It does not compute hashes, inspect a certificate tree, or maintain
an unchanged-pass counter.

## Data consolidation state

- M3 current repository: about 86 GB of raw data, 94,666 raw files, all regular
  files, no raw symlinks. The 81 GB previously hidden behind links to
  `defi-dominant-currency` were moved into this repository. Remaining unique raw
  evidence from that checkout is retained under
  `data/raw/archive/defi-dominant-currency/`; unconsumed derived data were removed.
- Studio current repository: about 155 GB and 314,806 regular raw files, including
  the roughly 62 GB Ethereum boundary absent on the M3. It has no raw symlinks.
  The remaining 411 MB of unique retired-repository raw evidence were moved under
  `data/raw/archive/defi-dominant-currency/studio-remaining-20260818/`, and the
  retired sibling data tree is empty.
- Cross-machine raw equality is not yet achieved because the Studio is reachable
  only through an unstable relay. Scientific work can proceed on the Studio, which
  owns the fuller raw boundary, while resumable path-and-size transfers fill the
  M3 copy.

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

The M3 now compiles a 47-page paper and a 37-page deck after both registered
reruns. The paper log is clean; the deck's result pages were visually inspected
and its two layout overflows corrected. There is one manuscript under `paper/`
and one presentation under `deck/`; Git history is the archive.
