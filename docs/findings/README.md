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
  D raw data and reconstruction           STUDIO CANONICAL OWNER; M3 BUILD COPY INTENTIONALLY PARTIAL
  |
D3 purpose-built analysis inputs        READY ON BOTH HOSTS FOR ACTIVE CLAIMS
  |
E0 exploration                          DONE
  |
E1 confirmatory specification lock      DONE
  |
F registered confirmatory rebuilds      DONE; FINDINGS GATE GREEN
  |
G baseline JFE paper                    DONE LOCALLY; CLEAN 47-PAGE PDF
  |
H baseline presentation deck            DONE LOCALLY; CLEAN 36-PAGE PDF
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
looking. It still keeps a presentable paper and deck rebuilt with clearly
labelled provisional, registered, or confirmed evidence.

The loop targets the making of vehicle dominance (features, drivers, adoption,
reversal, persistence, and conditional choice) and liquidity-provision behavior
(capital stocks, liquidity-supply flows, provider entry/exit, reallocation, and
V3/V4 routing or netting behavior where inputs support it). A candidate result
can become headline evidence only after it states the unit, conditioning set,
economic magnitude, strongest rival explanation, literature contribution, and
complete producer-to-deliverable path. Provisional results may still enter the
paper and deck if they are explicitly labelled and reproducible enough for
review.

Routing maturation, direct-cost dominance, the joint V2/V3 capital-flow family,
rent incidence, and persistence/hysteresis are blocked, withheld, supporting, or
outside the executable perimeter until they receive a complete
producer-to-deliverable path. They must not be presented as established findings.

## Current blockers

- The Studio checkout is the canonical raw-data owner. Its raw boundary is
  complete and is not duplicated byte-for-byte onto M3 because the only route
  between the hosts is a heavily throttled relay. M3 retains the code, generated
  deliverables, and the active processed inputs needed for review.
- Studio has no LaTeX toolchain; the final paper/deck compile gate is therefore
  run on M3, while Studio stores the same source and already-built PDFs.

The executable check is:

```bash
./scripts/run scripts/verify/audit_findings_freeze.py
```

It checks declared paths and whether every active output is newer than its inputs
and the lock.

## Data consolidation state

- M3 current repository: about 87 GB of raw data, all regular files and no raw
  symlinks. The data recovered from `defi-dominant-currency` were moved into this
  repository; unconsumed derived data were removed. M3 is the TeX/build and review
  host, not the canonical raw store.
- Studio current repository: about 158 GB and 700,412 regular raw files, including
  the complete Ethereum boundary and the explicit
  `data/raw/ethereum/rpc_cache/`. It has no raw symlinks. The recovered backup
  folder is inside `data/raw/archive/defi-vehicle-currencies-backups/`; the
  retired sibling checkout has been removed from the projects directory and no
  top-level backup checkout remains.
- Stale runtime caches and derived artifacts were removed from both checkouts
  (recoverable copies are in each machine's Trash).
  Raw RPC cache records were moved into `data/raw/ethereum/rpc_cache/` before the
  runtime cleanup. Cross-machine raw equality is intentionally not claimed: Studio
  is the owner and M3's smaller copy is a working/build copy.

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

The M3 compiles a 47-page paper and a 36-page deck after both registered reruns.
The paper log is clean; the deck's result pages were visually inspected and its
two layout overflows corrected. Studio contains the same source and PDFs and
passes the findings freeze plus the full repository test suite. There is one
manuscript under `paper/` and one presentation under `deck/`; Git history is the
archive.

These are baseline deliverables, not final submission deliverables. The paper
and deck should remain presentable throughout the research process. Before the
submission freeze, they need expanded mechanism results and a motivation rewrite
built around concrete, down-to-earth vehicle-currency examples from traditional
finance. If that expansion does not reach the JFE bar, the correct action is
more search while maintaining the current draft and review snapshot, not a global
pause.
