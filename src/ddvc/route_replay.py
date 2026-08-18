"""Build one authentic, selectable route trace for the talk's local replay."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ddvc.asset_types import canonical_token
from ddvc.realised import LINEAR_ROUTE_COLUMNS, extract_linear_realised_routes
from ddvc.runtime import atomic_output

SCHEMA_VERSION = "dvc-route-replay-v1"


def _label(symbol: object, address: object) -> str:
    value = str(symbol or "").strip()
    if value and value.lower() not in {"nan", "none"}:
        return value
    token = canonical_token(address) or str(address)
    return f"{token[:6]}…{token[-4:]}" if len(token) > 12 else token


def _finite(value: object, name: str) -> float:
    number = float(value)
    if not pd.notna(number):
        raise ValueError(f"route replay {name} is not finite")
    return number


def build_route_replay_manifest(
    legs: pd.DataFrame,
    *,
    day: str,
    tx_hash: str,
    component_id: int,
) -> dict[str, object]:
    """Describe an exact two-leg route without rendering workflow metadata."""

    missing = sorted(set(LINEAR_ROUTE_COLUMNS) - set(legs.columns))
    if missing:
        raise ValueError(f"route replay input is missing columns: {', '.join(missing)}")
    if not str(day).isdigit() or len(str(day)) != 8:
        raise ValueError("route replay day must be YYYYMMDD")
    transaction = str(tx_hash).lower()
    selected = legs[
        legs["tx_hash"].astype(str).str.lower().eq(transaction)
        & pd.to_numeric(legs["component_id"], errors="coerce").eq(int(component_id))
    ].copy()
    if selected.empty:
        raise ValueError("route replay transaction component is absent")

    routes = extract_linear_realised_routes(selected)
    if len(routes) != 1:
        raise ValueError("route replay requires exactly one coherent two-leg vehicle route")
    route = routes.iloc[0]
    source = canonical_token(route["src"])
    vehicle = canonical_token(route["vehicle"])
    target = canonical_token(route["tgt"])
    ordered: list[pd.Series] = []
    for token_in, token_out in ((source, vehicle), (vehicle, target)):
        candidates = selected[
            selected["token_in"].map(canonical_token).eq(token_in)
            & selected["token_out"].map(canonical_token).eq(token_out)
        ]
        if len(candidates) != 1:
            raise ValueError("route replay legs do not form one linear source-vehicle-target path")
        ordered.append(candidates.iloc[0])

    first, second = ordered
    timestamp = int(route["timestamp_utc"])
    return {
        "schema_version": SCHEMA_VERSION,
        "day": str(day),
        "timestamp_utc": timestamp,
        "timestamp_iso": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
        "tx_hash": transaction,
        "component_id": int(component_id),
        "route": {
            "source": _label(first["token_in_sym"], first["token_in"]),
            "vehicle": _label(first["token_out_sym"], first["token_out"]),
            "target": _label(second["token_out_sym"], second["token_out"]),
            "input_amount": _finite(first["amount_in"], "input amount"),
            "output_amount": _finite(second["amount_out"], "output amount"),
            "value_usd": _finite(route["usd"], "value"),
            "endpoint_value_ratio": _finite(route["endpoint_value_ratio"], "endpoint value ratio"),
            "venues": [str(first["source"]), str(second["source"])],
            "legs": [
                {
                    "step": 1,
                    "log_index": int(first["log_index"]),
                    "venue": str(first["source"]),
                    "token_in": _label(first["token_in_sym"], first["token_in"]),
                    "token_out": _label(first["token_out_sym"], first["token_out"]),
                    "amount_in": _finite(first["amount_in"], "hop-one input"),
                    "amount_out": _finite(first["amount_out"], "hop-one output"),
                },
                {
                    "step": 2,
                    "log_index": int(second["log_index"]),
                    "venue": str(second["source"]),
                    "token_in": _label(second["token_in_sym"], second["token_in"]),
                    "token_out": _label(second["token_out_sym"], second["token_out"]),
                    "amount_in": _finite(second["amount_in"], "hop-two input"),
                    "amount_out": _finite(second["amount_out"], "hop-two output"),
                },
            ],
        },
    }


def _amount(value: object) -> str:
    number = float(value)
    if abs(number) >= 100_000:
        return f"{number:,.0f}"
    if abs(number) >= 100:
        return f"{number:,.2f}"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


def _venue_label(value: object) -> str:
    return str(value).replace("_", " ").title()


def _validated_route(
    manifest: dict[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("route replay manifest schema is unsupported")
    route = manifest.get("route")
    if not isinstance(route, dict) or not isinstance(route.get("legs"), list) or len(route["legs"]) != 2:
        raise ValueError("route replay manifest must contain two legs")
    legs = route["legs"]
    if not all(isinstance(leg, dict) for leg in legs):
        raise ValueError("route replay legs must be objects")
    return route, legs


def render_route_replay_html(manifest: dict[str, object]) -> str:
    """Return a self-contained progressive replay with a complete print frame."""

    route, legs = _validated_route(manifest)
    first, second = legs
    esc = lambda value: html.escape(str(value), quote=True)
    transaction = str(manifest.get("tx_hash") or "")
    short_tx = f"{transaction[:10]}…{transaction[-8:]}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Executed route replay</title>
<style>
:root{{--ink:#1c1f24;--muted:#626871;--ucl:#371c5c;--bright:#9132ff;--stable:#007d6c;--panel:#f6f7f9;--line:#d6dae0}}
*{{box-sizing:border-box}} body{{margin:0;background:#fff;color:var(--ink);font:18px/1.4 Inter,Arial,sans-serif}}
main{{max-width:1180px;margin:auto;padding:44px 54px}} h1{{margin:0 0 6px;font-size:38px}} .kicker{{color:var(--ucl);font-weight:750}}
.meta{{display:flex;gap:18px;flex-wrap:wrap;color:var(--muted);font-size:14px}} .meta code{{user-select:text}}
.route{{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:center;gap:16px;margin:72px 0 44px}}
.token{{border:2px solid var(--line);border-radius:50%;width:150px;height:150px;display:grid;place-items:center;text-align:center;font-size:24px;font-weight:800;background:white}}
.token.vehicle{{border-color:var(--bright);box-shadow:0 0 0 9px #f2e9ff}}
.leg{{min-width:210px;opacity:.22;transform:translateY(8px);transition:.4s ease}} .leg.active{{opacity:1;transform:none}}
.arrow{{height:4px;background:var(--ucl);position:relative;margin-bottom:12px}} .arrow:after{{content:"";position:absolute;right:-1px;top:-7px;border-left:14px solid var(--ucl);border-top:9px solid transparent;border-bottom:9px solid transparent}}
.venue{{display:inline-block;border-radius:999px;background:var(--panel);padding:5px 10px;font-size:14px;font-weight:750}} .amount{{margin-top:7px;font-size:15px}}
.summary{{border-left:5px solid var(--stable);background:#eef8f5;padding:18px 22px;font-size:20px}} .summary strong{{color:var(--stable)}}
.controls{{display:flex;align-items:center;gap:10px;margin-top:26px}} button{{border:1px solid var(--line);border-radius:8px;background:white;padding:10px 15px;font:inherit;cursor:pointer}} button.primary{{background:var(--ucl);color:white;border-color:var(--ucl)}}
@media(max-width:850px){{main{{padding:28px 22px}}.route{{grid-template-columns:1fr;justify-items:center;margin:38px 0}}.leg{{width:min(420px,90vw)}}.arrow{{transform:rotate(90deg);width:100px;margin:34px auto}}}}
@media print{{main{{padding:24px}}.controls{{display:none}}.leg{{opacity:1;transform:none}}}}
</style></head><body><main>
<div class="kicker">ONE EXECUTED TRANSACTION</div><h1>Routing through a vehicle currency</h1>
<div class="meta"><span>{esc(manifest.get('timestamp_iso'))}</span><span>component {esc(manifest.get('component_id'))}</span><code title="{esc(transaction)}">{esc(short_tx)}</code></div>
<div class="route">
  <div class="token">{esc(route.get('source'))}</div>
  <div class="leg" data-step="1"><div class="arrow"></div><span class="venue">{esc(_venue_label(first.get('venue')))}</span><div class="amount">{esc(_amount(first.get('amount_in')))} {esc(first.get('token_in'))} → {esc(_amount(first.get('amount_out')))} {esc(first.get('token_out'))}</div></div>
  <div class="token vehicle">{esc(route.get('vehicle'))}<small style="display:block;font-size:13px;color:var(--muted)">vehicle</small></div>
  <div class="leg" data-step="2"><div class="arrow"></div><span class="venue">{esc(_venue_label(second.get('venue')))}</span><div class="amount">{esc(_amount(second.get('amount_in')))} {esc(second.get('token_in'))} → {esc(_amount(second.get('amount_out')))} {esc(second.get('token_out'))}</div></div>
  <div class="token">{esc(route.get('target'))}</div>
</div>
<div class="summary"><strong>{esc(_amount(route.get('value_usd')))} USD</strong> crossed {esc(len(set(route.get('venues') or [])))} venues in one coherent route.</div>
<div class="controls"><button id="back">Back</button><button id="next" class="primary">Reveal next leg</button><button id="all">Show complete route</button><span id="state" class="meta">0 of 2 legs</span></div>
</main><script>
let step=0; const legs=[...document.querySelectorAll('.leg')]; const state=document.getElementById('state');
function show(n){{step=Math.max(0,Math.min(2,n));legs.forEach((x,i)=>x.classList.toggle('active',i<step));state.textContent=`${{step}} of 2 legs`;}}
document.getElementById('next').onclick=()=>show(step+1);document.getElementById('back').onclick=()=>show(step-1);document.getElementById('all').onclick=()=>show(2);document.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key===' ')show(step+1);if(e.key==='ArrowLeft')show(step-1)}});show(0);
</script></body></html>"""


def render_route_replay_deck_values(manifest: dict[str, object]) -> str:
    """Bind slide labels to the same admitted route used by the live replay."""

    route, legs = _validated_route(manifest)
    first, second = legs

    def amount(value: object) -> str:
        return f"{float(value):,.0f}"

    return "\n".join(
        [
            "% Generated by scripts/plot/build_route_replay.py; do not edit.",
            f"\\newcommand{{\\RouteReplayInputAmount}}{{{amount(first['amount_in'])}}}",
            f"\\newcommand{{\\RouteReplayVehicleAmount}}{{{amount(first['amount_out'])}}}",
            f"\\newcommand{{\\RouteReplayOutputAmount}}{{{amount(second['amount_out'])}}}",
            f"\\newcommand{{\\RouteReplayValue}}{{{amount(route['value_usd'])}}}",
            "",
        ]
    )


def write_route_replay_bundle(
    manifest: dict[str, object], *, manifest_path: Path, html_path: Path, tex_path: Path
) -> tuple[Path, Path, Path]:
    """Atomically install the manifest and both of its direct consumers."""

    with atomic_output(manifest_path) as temporary:
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with atomic_output(html_path) as temporary:
        temporary.write_text(render_route_replay_html(manifest), encoding="utf-8")
    with atomic_output(tex_path) as temporary:
        temporary.write_text(render_route_replay_deck_values(manifest), encoding="utf-8")
    return manifest_path, html_path, tex_path


def manifest_from_partition(
    path: Path, *, day: str, tx_hash: str, component_id: int
) -> dict[str, object]:
    """Read one route partition into the replay."""

    legs = pd.read_parquet(path, columns=LINEAR_ROUTE_COLUMNS)
    return build_route_replay_manifest(
        legs,
        day=day,
        tx_hash=tx_hash,
        component_id=component_id,
    )
