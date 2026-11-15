"""Build a local static performance dashboard from a HyperSpeed JSON report.

No remote scripts, URLs, device identifiers, or source operation payloads.
This dashboard distinguishes synthetic fixture time from real UDB telemetry.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def render(report):
    if not isinstance(report, dict) or report.get("schema") != 1:
        raise ValueError("Invalid HyperSpeed report")
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, dict) or len(scenarios) > 100:
        raise ValueError("Invalid or oversized HyperSpeed report")
    ranked = sorted(scenarios.items(), key=lambda kv: kv[1]["p95_ms"], reverse=True)
    high = max([r["p95_ms"] for _, r in ranked] + [0.0001])
    rows = []
    for name, row in ranked:
        label = html.escape(name)
        bar = min(100, max(0.5, 100 * row["p95_ms"] / high))
        cold = row.get("cold") or {}
        warm = row.get("warm") or {}
        resources = row.get("resources") or {}
        observed_rss = resources.get("observed_rss_bytes")
        rss = "n/a" if observed_rss is None else f"{observed_rss / 1048576:.1f}"
        rows.append(
            "<tr>"
            f"<td><strong>{label}</strong><div class='barbox'>"
            f"<div class='bar' style='width:{bar:.1f}%'></div></div></td>"
            f"<td>{row['count']}</td>"
            f"<td>{row['p50_ms']:.4f}</td>"
            f"<td>{row['p95_ms']:.4f}</td>"
            f"<td>{row['p99_ms']:.4f}</td>"
            f"<td>{cold.get('p50_ms', 0):.4f}</td>"
            f"<td>{warm.get('p50_ms', 0):.4f}</td>"
            f"<td>{rss}</td></tr>"
        )
    trace_rows = []
    for name, row in sorted(report.get("observed_trace_stages", {}).items()):
        trace_rows.append(
            f"<tr><td>{html.escape(name)}</td><td>{row['count']}</td>"
            f"<td>{row['p50_ms']:.4f}</td><td>{row['p95_ms']:.4f}</td></tr>"
        )
    note = html.escape(report.get("disclaimer", ""))
    mode = html.escape(str(report.get("mode", "unknown")))
    num = int(report.get("scenario_count", 0))
    samples = int(report.get("sample_count", 0))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UDB HyperSpeed baseline dashboard</title>
<style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif}}
body{{background:#0e1622;color:#ecf3fb;margin:0 auto;padding:36px;max-width:1150px}}
h1{{font-size:28px;letter-spacing:-.7px}}
.subtitle{{color:#a9bdcc}}
.summary{{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}}
.card{{border:1px solid #30465a;background:#142434;border-radius:12px;padding:18px;flex:1;min-width:170px}}
.card strong{{display:block;font-size:22px;margin:6px 0}}
.warning{{padding:14px 16px;border:1px solid #926f3e;border-radius:10px;background:#30271d;margin:14px 0}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:11px 8px;border-bottom:1px solid #30465a;font-size:13px}}
th{{color:#b2c6d7}}
.barbox{{height:4px;background:#283b4c;border-radius:6px;margin-top:8px;width:100%}}
.bar{{height:4px;background:#69a6dc;border-radius:6px}}
section{{margin-top:32px;overflow-x:auto}}
</style></head><body>
<h1>UDB HyperSpeed 2.0</h1>
<p class="subtitle">Source-controlled benchmark reporting • Mode: {mode}</p>
<div class="warning">{note} No unverified speedup is claimed.</div>
<div class="summary">
<div class="card">Workflow shapes<strong>{num}</strong></div>
<div class="card">Timing samples<strong>{samples}</strong></div>
<div class="card">Overall p95<strong>{report["overall"]["p95_ms"]:.4f} ms</strong></div>
<div class="card">Overall p99<strong>{report["overall"]["p99_ms"]:.4f} ms</strong></div>
</div>
<section><h2>Per-workflow latency</h2><table>
<thead><tr><th>Fixture workflow</th><th>n</th><th>p50 (ms)</th>
<th>p95 (ms)</th><th>p99 (ms)</th><th>Cold p50</th>
<th>Warm p50</th><th>RSS observed (MiB)</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>
<section><h2>Opt-in real UDB trace phases</h2><table>
<thead><tr><th>Stage</th><th>n</th><th>p50 (ms)</th><th>p95 (ms)</th></tr></thead>
<tbody>{"".join(trace_rows) or '<tr><td colspan="4">No live trace supplied</td></tr>'}</tbody>
</table></section>
<p class="subtitle">Critical-path and resource details are available in the companion JSON.
Only fixed telemetry fields are recorded, never commands or user content.</p>
</body></html>
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.input.is_symlink() or args.input.stat().st_size > 8 * 1048576:
        parser.error("Unsafe or oversized report file")
    report = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.write_text(render(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
