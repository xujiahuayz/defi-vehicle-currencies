# Table Rendering and Manuscript Lineage

`scripts/tabulate/` owns generic table fragments and their standalone inspection PDFs. A renderer writes `output/tables/<stem>.tex` and `<stem>.pdf`; `write_table_artifacts` also records the renderer, declared scientific code, declared inputs, and exact output bytes under `data/manifests/output/tables/`.

The paper owns captions, labels, notes, placement, and numbering. A table becomes a deliverable input only when the paper or deck explicitly consumes it and its payload and provenance are current.

## Named renderers

| Renderer | Inputs | Current status and consumer |
|---|---|---|
| `render_data_coverage.py` | `data/processed/raw_data_inventory.parquet` | Runnable inspection table; no current paper or deck consumer. |
| `render_variable_notation.py` | `src/ddvc/variable_registry.py` | Runnable notation audit; no current paper or deck consumer. |
| `render_summary_statistics.py` | `data/processed/observations_token_day.parquet` through `DEFAULT_OBSERVATIONS_TABLE` | Input and renderer are present, but no generated fragment is checked in and there is no current deliverable consumer. |
| `render_sample_coverage.py` | `bridge_daily`, `route_cost_panel_v2`, LP-capital concentration, and V4 route-unit panels | Blocked. `route_cost_panel_v2` is withdrawn pending its registered rebuild. Do not run or cite the checked-in fragment meanwhile. |
| `render_dominance_rotation.py` | Certified `intermediation_complexity_rival.jsonl` and sidecar | Current paper body for `tab:rotation`; selects the exact two-leg count and within-20\% supported-value rows. |
| `render_pair_composition.py` | Certified pair-decomposition presentation binding and fixed-effect exhibit, with both sidecars | Current paper body for `tab:pair-composition`; Panels A--B are the certified accounting and Panel C contains all three descriptive fixed-effect rows. |
| `render_provisional_results_deck_values.py` | Nine certified route-composition, excess-use, integration, venue-rival, and router-window JSONL exhibits, with their sidecars | Current shared paper/deck binding. The values remain provisional in scientific scope, but the generated TeX is reproducible and provenance-stamped. Several producer guards withhold the entire macro set when a sentence in the manuscript stops holding. |
| `render_usdt_transition.py` | Certified `provisional_results_deck_values.tex` and sidecar | Current paper body for `tab:usdt-transition`; both the table and its upstream macro binding are generated and provenance-stamped. |
| `render_venue_coverage.py` | Certified `venue_volume_by_year.jsonl` and sidecar | Current paper body for `tab:app:venues`; validates the nine-source observed-volume denominator, fixes the venue order, discloses Fluid's partial dates, and computes the pooled row from 2020--2026 USD volume. |
| `render_venue_technology_rival.py` | Certified `venue_technology_rival.jsonl` and sidecar | Current paper body for `tab:venue-technology`; a route component enters a venue family only when every leg belongs to it, and a scope-year with no route component is labelled separately from one whose components carry no intermediation. |
| `render_routing_technology_windows.py` | Certified `routing_technology_windows.jsonl` and sidecar | Current paper body for `tab:router-windows`; validates the symmetric pre/post windows around three dated public router releases, requires the two periods of a release to span equal observed calendars, and refuses the table if the balanced five-venue perimeter stops reproducing the full perimeter. |

## Tables in the current manuscript

Six of the manuscript's thirteen tables have one-to-one `scripts/tabulate/` renderers and are consumed as generated body fragments. The other seven table bodies remain inline and presentation-owned, even when their values come from generated exhibits. “Inline” means the values must still be checked against the listed source; it does not make the TeX table a data release.

| Manuscript label | Presentation owner | Quantitative source | Status |
|---|---|---|---|
| `tab:panel` | `paper/sections/02-setting.tex` | `unified_route_quality.jsonl`; `round_trip_share_by_day.jsonl` | Active, inline, hand-transcribed from stamped exhibits. |
| `tab:rotation` | `paper/sections/03-dominance.tex` inputs `output/tables/dominance_rotation.tex` | Certified `intermediation_complexity_rival.jsonl` | Active generated body with a one-to-one renderer and provenance-stamped TeX/PDF outputs. |
| `tab:pair-composition` | `paper/sections/03-dominance.tex` inputs `output/tables/pair_composition.tex` | Certified pair-decomposition macros and all three rows of `vehicle_transition_pair_fixed_effects.jsonl` | Active generated body with a one-to-one renderer and provenance-stamped TeX/PDF outputs. |
| `tab:usdt-transition` | `paper/sections/03-dominance.tex` inputs `output/tables/usdt_transition.tex` | Certified `provisional_results_deck_values.tex`, itself generated from the current manifested route exhibits | Active generated body with provenance-stamped TeX/PDF outputs and a generated, stamped upstream binding. |
| `tab:router-windows` | `paper/sections/05-rivals.tex` inputs `output/tables/routing_technology_windows.tex` | Certified `routing_technology_windows.jsonl` | Active generated body with a one-to-one renderer and provenance-stamped TeX/PDF outputs. |
| `tab:venue-technology` | `paper/sections/05-rivals.tex` inputs `output/tables/venue_technology_rival.tex` | Certified `venue_technology_rival.jsonl` | Active generated body with a one-to-one renderer and provenance-stamped TeX/PDF outputs. |
| `tab:app:cl` | `paper/sections/08-appendix.tex` | `v4_quoter_validation.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:curve` | `paper/sections/08-appendix.tex` | `curve_quoter_validation.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:weighted` | `paper/sections/08-appendix.tex` | `weighted_quoter_validation.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:support` | `paper/sections/08-appendix.tex` | `quoter_support_bounds.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |
| `tab:app:venues` | `paper/sections/08-appendix.tex` inputs `output/tables/venue_coverage.tex` | Certified `venue_volume_by_year.jsonl` | Active generated body with a one-to-one renderer, nine-source annual sum checks, fixed venue order, Fluid partial-date disclosure, pooled-volume calculation, and provenance-stamped TeX/PDF outputs. |
| `tab:app:curveleg` | `paper/sections/08-appendix.tex` | `docs/venue-coverage-bounds.md` and its named Curve-exclusion exhibits | Active, inline, hand-transcribed from the review record. |
| `tab:app:roundtrip` | `paper/sections/08-appendix.tex` | `round_trip_share_by_day.jsonl` | Active, inline, hand-transcribed from a stamped exhibit. |

The remaining migration should create one descriptive renderer per inline empirical table and have the manuscript input its fragment. Captions and notes remain in the manuscript. Migrate each table and its tests atomically; do not duplicate an inline table while leaving both copies live.

Before removing an older file from `output/tables/`, search paper, deck, scripts, tests, docs, and manifests for consumers. Git history is the archive only after a current owner and every live reference have been reconciled.
