# DVC executor entrypoint

This repository is one continuous research project. Before changing anything, run:

```bash
./scripts/run scripts/research_action_preflight.py <data|analysis|deck|prose>
```

The preflight reads the live graph state in `docs/findings-freeze.md` and routes the action to the relevant standing decisions in `docs/research-workflow.md`. A red or closed action is a refusal, not advice to work around the gate.

Then read, in this order:

1. The last 80 lines of `logs/grind-ledger.md` and every unchecked item in `logs/grind-queue.md`.
2. The current-node and definition guards in `docs/findings-freeze.md`.
3. Only the relevant workflow section named by the preflight. Search that section and the ledger for prior corrections before proposing a new method, memo, study, or wording pass.

Standing correction rules:

- A written decision outranks a plausible fresh plan. Reopen it only with new scientific evidence and record why.
- Do not repeat a known failed approach under new vocabulary. In particular, word substitution is not prose revision. The live prose state is tiered: publication-standard prose may evolve for the question, setting, mechanisms, and certified route-only facts, while final cost, turnover, persistence, LP-return, and other exact-state coefficient sentences remain excluded until their own evidence locks. When the full prose node opens, rewrite every affected section from its economic argument at sentence and paragraph level. Cards locate the relevant comparison, but direct passages from the published JFE text govern rhetorical imitation; the passage map is in workflow section 1. Venue-shape and vocabulary checks are final diagnostics only.
- Do not commission another undirected corpus read when the required full-text cards, optics records, or measured venue bands already exist. Inspect the durable records first and extend their missing field in place. When a prose claim lacks sentence- or paragraph-level support, return to the named raw published passage rather than extrapolating from a summary card.
- Data work begins with economic materiality and concentration. Metadata or coverage dirt blocks only when it can change identity, sample composition, an estimate, or inference.
- Calendar time is not treatment. Separate adoption, use, exit, availability reversal, opportunity-set change, and cost-state reversal.
- The deck is always presentation-ready. Every touch follows: semantic/source diff, focused tests, compile, evidence/language/status audits, changed-page inspection, then commit.

Knowledge and consumer routing:

- A consumer is an executable caller, a paper/deck include, a canonical workflow or agent route, or a current index/review that requires the artifact. A search hit, self-reference, generic directory mention, or the possibility that an agent may discover a file is not a consumer.
- Current literature claims route through `literature/source-admission.json`, `literature/vehicle-currencies.bib`, `docs/reviews/README.md`, and `docs/literature-audit.md`. Files under `literature/reviews/` are historical discovery aids only.
- Deck-craft calibration routes through `docs/reviews/deck-venue-exemplars.md`; current visual inspections route through the named ledgers indexed in `docs/reviews/README.md`.
- `output/` is reserved for command-generated handoff artifacts. Do not add authored memos, literature digests, or agent handoffs there.

Java's interjections are for new discoveries, scientific choices, and redirection. Recovering an existing instruction is the executor's responsibility.
