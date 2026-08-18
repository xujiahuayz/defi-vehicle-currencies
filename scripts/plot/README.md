# Plot

Plotters reshape processed panels or analysis exhibits for presentation; they do
not read raw data or define a new estimand.

| Owner | Output and consumer |
|---|---|
| `build_vehicle_excess_use_transition.py` | transition figure used by paper/deck |
| `build_within_day_contrasts.py` | within-day role-contrast figure used by paper/deck |
| `build_visual_experiments.py` | named experimental figures used by the deck |
| `build_route_replay.py` | route-replay manifest, interactive HTML, and deck macros |

Edit the owner, never the generated PDF/HTML. An unconsumed figure is removed
from the live tree.
