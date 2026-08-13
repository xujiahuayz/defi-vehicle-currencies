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
- Do not repeat a known failed approach under new vocabulary. In particular, word substitution is not prose revision. While prose node P is closed, develop content in `docs/paper-spine.md`; do not edit `paper/`. When P opens, rewrite an affected section from its economic argument at sentence and paragraph level, using the stored JFE cards and venue-shape evidence. The vocabulary checks are final diagnostics only.
- Do not commission another corpus read when the required full-text cards, optics records, or measured venue bands already exist. Inspect the durable records first and extend their missing field in place.
- Data work begins with economic materiality and concentration. Metadata or coverage dirt blocks only when it can change identity, sample composition, an estimate, or inference.
- Calendar time is not treatment. Separate adoption, use, exit, availability reversal, opportunity-set change, and cost-state reversal.
- The deck is always presentation-ready. Every touch follows: semantic/source diff, focused tests, compile, evidence/language/status audits, changed-page inspection, then commit.

Java's interjections are for new discoveries, scientific choices, and redirection. Recovering an existing instruction is the executor's responsibility.
