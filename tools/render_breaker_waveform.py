#!/usr/bin/env python3
"""Render 3-phase breaker short-circuit/TRV waveforms to SVG (stdlib only)."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

PHASE_SHIFT = [0.0, -2 * math.pi / 3, 2 * math.pi / 3]


def find_next_current_zero(t_cmd: float, phi: float, omega: float) -> float:
    target = omega * t_cmd + phi
    k = math.ceil(target / math.pi)
    return (k * math.pi - phi) / omega


def build_wave(
    rated_voltage_kv: float,
    rated_current_ka: float,
    frequency_hz: float,
    kpp: float,
    xr: float,
    fault_angle_deg: float,
    trip_time_ms: float,
    t_max_ms: float,
    samples: int,
):
    v_ll = rated_voltage_kv * 1000.0
    i_rms = rated_current_ka * 1000.0
    omega = 2 * math.pi * frequency_hz

    v_peak = (v_ll / math.sqrt(3)) * math.sqrt(2)
    i_peak = i_rms * math.sqrt(2)
    tau = xr / omega

    t_max = t_max_ms / 1000.0
    t_cmd = trip_time_ms / 1000.0
    dt = t_max / (samples - 1)
    fault_angle = math.radians(fault_angle_deg)

    t = [i * dt for i in range(samples)]
    open_times = [find_next_current_zero(t_cmd, ph, omega) for ph in PHASE_SHIFT]

    v = [[0.0] * samples for _ in range(3)]
    i_cur = [[0.0] * samples for _ in range(3)]
    trv = [[0.0] * samples for _ in range(3)]
    trv_sum = [0.0] * samples

    max_abs = 1.0

    for idx_time, tt in enumerate(t):
        trv_mix = 0.0
        for ph_idx, sh in enumerate(PHASE_SHIFT):
            vs = v_peak * math.sin(omega * tt + sh)
            i_sym = i_peak * math.sin(omega * tt + sh)
            dc_offset = -i_peak * math.sin(fault_angle + sh) * math.exp(-tt / tau)
            i_raw = i_sym + dc_offset

            interrupted = tt >= open_times[ph_idx]
            i_val = 0.0 if interrupted else i_raw

            trv_val = 0.0
            if interrupted:
                td = tt - open_times[ph_idx]
                w_n = 2.3 * omega
                damp = math.exp(-td / (0.75 * tau))
                sign_term = 1.0 if math.sin(omega * open_times[ph_idx] + sh) >= 0 else -1.0
                trv_val = kpp * v_peak * (1 - math.cos(w_n * td)) * damp * sign_term

            v[ph_idx][idx_time] = vs
            i_cur[ph_idx][idx_time] = i_val
            trv[ph_idx][idx_time] = trv_val
            trv_mix += trv_val

            max_abs = max(max_abs, abs(vs), abs(i_val), abs(trv_val))

        trv_sum[idx_time] = trv_mix / 3.0
        max_abs = max(max_abs, abs(trv_sum[idx_time]))

    return {
        "t": t,
        "v": v,
        "i": i_cur,
        "trv": trv_sum,
        "open_times": open_times,
        "tau": tau,
        "trv_peak": kpp * v_peak,
        "max_abs": max_abs,
    }


def points(xs, ys) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))


def render_svg(data: dict, output: Path, title: str, t_max_ms: float):
    width, height = 1400, 900
    l, r, top, b = 70, 24, 34, 38
    chart_h = (height - top - b - 30) / 3
    chart_w = width - l - r

    zone_titles = [
        "Voltage Va/Vb/Vc",
        "Current Ia/Ib/Ic (interrupted => 0)",
        "TRV (phase average)",
    ]
    zone_y = [top, top + chart_h + 15, top + (chart_h + 15) * 2]

    max_abs = data["max_abs"]
    t_ms = [x * 1000.0 for x in data["t"]]

    def map_x(tval_ms: float) -> float:
        return l + (tval_ms / t_max_ms) * chart_w

    def map_y(zy: float, v: float) -> float:
        return zy + chart_h * (0.5 - 0.46 * (v / max_abs))

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0a1022"/>',
        f'<text x="{width/2:.1f}" y="22" fill="#ecf1ff" text-anchor="middle" font-size="17">{title}</text>',
    ]

    for zy, zt in zip(zone_y, zone_titles):
        svg.append(f'<rect x="{l}" y="{zy:.2f}" width="{chart_w:.2f}" height="{chart_h:.2f}" fill="#0c152b" stroke="#30406b"/>')
        for gx in range(13):
            x = l + gx * chart_w / 12
            svg.append(f'<line x1="{x:.2f}" y1="{zy:.2f}" x2="{x:.2f}" y2="{zy+chart_h:.2f}" stroke="#2e3d66" stroke-width="1"/>')
        for gy in range(9):
            y = zy + gy * chart_h / 8
            svg.append(f'<line x1="{l}" y1="{y:.2f}" x2="{l+chart_w:.2f}" y2="{y:.2f}" stroke="#2e3d66" stroke-width="1"/>')
        svg.append(f'<text x="{l+7}" y="{zy+16:.2f}" fill="#a8b2d3" font-size="12">{zt}</text>')

    colors = ["#ff6b6b", "#4ecdc4", "#ffe66d"]
    x_vals = [map_x(tm) for tm in t_ms]

    for idx in range(3):
        yv = [map_y(zone_y[0], val) for val in data["v"][idx]]
        yi = [map_y(zone_y[1], val) for val in data["i"][idx]]
        svg.append(f'<polyline fill="none" stroke="{colors[idx]}" stroke-width="1.3" points="{points(x_vals, yv)}"/>')
        svg.append(f'<polyline fill="none" stroke="{colors[idx]}" stroke-width="1.5" points="{points(x_vals, yi)}"/>')

    y_trv = [map_y(zone_y[2], val) for val in data["trv"]]
    svg.append(f'<polyline fill="none" stroke="#c792ea" stroke-width="1.8" points="{points(x_vals, y_trv)}"/>')

    for ot in data["open_times"]:
        x_ot = map_x(ot * 1000.0)
        svg.append(
            f'<line x1="{x_ot:.2f}" y1="{top:.2f}" x2="{x_ot:.2f}" y2="{height-b:.2f}" '
            'stroke="#7fdbff" stroke-width="1.2" stroke-dasharray="6 4"/>'
        )

    summary = (
        f'Open(A/B/C)={data["open_times"][0]*1000:.2f}/{data["open_times"][1]*1000:.2f}/{data["open_times"][2]*1000:.2f} ms, '
        f'tau={data["tau"]*1000:.2f} ms, TRVpeak≈{data["trv_peak"]/1000:.1f} kV'
    )

    svg.extend([
        f'<text x="{l}" y="{height-10}" fill="#a8b2d3" font-size="12">0 ms</text>',
        f'<text x="{l+chart_w-50:.2f}" y="{height-10}" fill="#a8b2d3" font-size="12">{t_max_ms:.0f} ms</text>',
        f'<text x="{width/2:.1f}" y="{height-10}" fill="#a8b2d3" text-anchor="middle" font-size="12">{summary}</text>',
        '</svg>',
    ])

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render breaker waveform SVG without browser dependencies")
    p.add_argument("--rated-voltage-kv", type=float, default=170.0)
    p.add_argument("--rated-current-ka", type=float, default=50.0)
    p.add_argument("--frequency-hz", type=float, default=60.0)
    p.add_argument("--kpp", type=float, default=2.0)
    p.add_argument("--xr", type=float, default=15.0)
    p.add_argument("--fault-angle-deg", type=float, default=90.0)
    p.add_argument("--trip-time-ms", type=float, default=35.0)
    p.add_argument("--t-max-ms", type=float, default=120.0)
    p.add_argument("--samples", type=int, default=2200)
    p.add_argument("--output", type=Path, default=Path("artifacts/breaker_waveform.svg"))
    p.add_argument("--title", type=str, default="3-Phase Breaker Short-Circuit & TRV")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    data = build_wave(
        rated_voltage_kv=args.rated_voltage_kv,
        rated_current_ka=args.rated_current_ka,
        frequency_hz=args.frequency_hz,
        kpp=args.kpp,
        xr=args.xr,
        fault_angle_deg=args.fault_angle_deg,
        trip_time_ms=args.trip_time_ms,
        t_max_ms=args.t_max_ms,
        samples=args.samples,
    )
    render_svg(data, args.output, args.title, args.t_max_ms)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
