"""Reportes de trazabilidad (CSV + HTML) para CohortEngine."""
from __future__ import annotations

import csv
import html
import math
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .cohorts import CohortEngine

_CSS = """body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2937;background:#f9fafb}
h1{font-size:20px}h2{font-size:15px;margin:0 0 6px}.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin:14px 0}
table{border-collapse:collapse;width:100%;font-size:12px;margin-top:8px}th,td{padding:4px 6px;border-bottom:1px solid #f1f5f9;text-align:left}
th{background:#f3f4f6}.in{background:#dcfce7;color:#166534;border-radius:4px;padding:1px 5px}.out{color:#9ca3af}
.warn{background:#fef3c7;color:#92400e;border-radius:4px;padding:1px 6px;font-size:11px}.txt{color:#6b7280;font-size:12px}
.meta{font-size:12px;color:#6b7280}input{padding:6px;width:260px;margin-bottom:6px}.num{text-align:right;font-variant-numeric:tabular-nums}"""


def _ident(x):
    return x


def trazar(ce: CohortEngine, q, variantes: Sequence[str], transform: Callable = _ident):
    ps, est = ce.explicar(q, variantes)
    taus_b = [v for v in variantes if v.upper().startswith("B") and not v.upper().startswith("BH")]
    detalle = []
    for rank, p in enumerate(ps, 1):
        motivo = ("entra a " + ", ".join(v for v in taus_b if p.cohortes.get(v))) if any(p.cohortes.get(v) for v in taus_b) \
            else (f"sim {p.similitud:.3f} bajo todos los τ → solo A" if taus_b else "")
        detalle.append({"consulta": q, "previa": p.id, "rank_sim": rank, "similitud": round(p.similitud, 4),
                        "valor": p.valor, "valor_original": transform(p.valor),
                        **{f"en_{v}": p.cohortes[v] for v in variantes},
                        "empate_corte_K": p.empate_corte_k, "motivo": motivo})
    resumen = []
    for v in variantes:
        e = est[v]
        n_coh = len(ce.miembros(q, v))
        regla = ("sin historia" if e is None else
                 f"cohorte con {n_coh} < {ce.min_k} → se usa A" if e.uso_respaldo else f"mediana de {n_coh} miembros")
        resumen.append({"consulta": q, "variante": v, "n_cohorte": n_coh,
                        "valor_ref": None if e is None else e.valor,
                        "valor_ref_original": None if e is None else transform(e.valor),
                        "fuente": None if e is None else e.fuente, "regla": regla,
                        "empate_corte_K": v.upper() == "K" and ce.empate_en_corte(q)})
    return detalle, resumen


def _write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _fmt(x):
    if x is None:
        return "—"
    return f"{x:,.0f}".replace(",", ".") if abs(x) >= 100 else f"{x:.3f}"


def generar_reporte(ce: CohortEngine, consultas: Iterable, out_dir, variantes=("A", "B0.3", "B0.6", "BH0.6", "K"),
                    info: dict | None = None, transform: Callable = _ident, n_html: int = 50, top: int = 15,
                    titulo: str = "Trazabilidad de cohortes semánticas"):
    """
    Genera trazabilidad_detalle.csv, trazabilidad_resumen.csv y trazabilidad.html.

    info: {consulta: {"grupo":..., "atr":..., "texto":..., "real": valor_real (escala interna)}}
    transform: función para pasar de la escala interna a la original (p. ej. math.expm1 para log1p).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    info = info or {}
    D, R, casos = [], [], []
    for i, q in enumerate(consultas):
        q = str(q)
        det, res = trazar(ce, q, variantes, transform)
        real = (info.get(q) or info.get(_try_int(q)) or {}).get("real")
        for r in res:
            if real is not None and r["valor_ref"] is not None:
                y, yhat = transform(real), r["valor_ref_original"]
                r["real_original"] = y
                r["ape_pct"] = round(abs(yhat - y) / abs(y) * 100, 2) if y else None
            else:
                r["real_original"], r["ape_pct"] = None, None
        D += det
        R += res
        if i < n_html:
            casos.append((q, det, res, info.get(q) or info.get(_try_int(q)) or {}))
    _write_csv(out / "trazabilidad_detalle.csv", D)
    _write_csv(out / "trazabilidad_resumen.csv", R)
    _html(out / "trazabilidad.html", casos, variantes, top, titulo,
          f"{len(R) // max(len(variantes), 1)} consultas · variantes {', '.join(variantes)} · "
          f"min_k = {ce.min_k} (si no, respaldo A) · k = {ce.k} · solo historia previa del mismo grupo")
    return R


def mdape_por_variante(resumen: list[dict]) -> dict:
    by: dict = {}
    for r in resumen:
        if r.get("ape_pct") is not None:
            by.setdefault(r["variante"], []).append(r["ape_pct"])
    return {v: _median(xs) for v, xs in by.items()}


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2) if n else math.nan


def _try_int(q):
    try:
        return int(q)
    except (TypeError, ValueError):
        return q


def _html(path: Path, casos, variantes, top, titulo, meta):
    e = lambda x: html.escape(str(x))
    o = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(titulo)}</title><style>{_CSS}</style></head><body>",
         f"<h1>{e(titulo)}</h1><div class='meta'>{e(meta)}</div>",
         "<input placeholder='Filtrar por id, grupo o texto…' oninput=\"for(const c of document.querySelectorAll('.card'))"
         "c.style.display=c.innerText.toLowerCase().includes(this.value.toLowerCase())?'':'none'\">"]
    for q, det, res, inf in casos:
        o.append(f"<div class='card'><h2>Consulta {e(q)}{' · grupo ' + e(inf['grupo']) if inf.get('grupo') else ''}"
                 f"{' · atributos: ' + e(inf['atr']) if inf.get('atr') else ''}</h2>")
        if inf.get("texto"):
            o.append(f"<div class='txt'>{e(str(inf['texto'])[:300])}</div>")
        has_real = any(r.get("real_original") is not None for r in res)
        o.append("<table><tr><th>Variante</th><th class='num'>n</th><th class='num'>Valor ref.</th>"
                 + ("<th class='num'>Real</th><th class='num'>APE</th>" if has_real else "") + "<th>Regla</th></tr>")
        for r in res:
            row = f"<td>{e(r['variante'])}</td><td class='num'>{r['n_cohorte']}</td><td class='num'>{_fmt(r['valor_ref_original'])}</td>"
            if has_real:
                ape = "—" if r["ape_pct"] is None else f"{r['ape_pct']:.1f}%"
                row += f"<td class='num'>{_fmt(r['real_original'])}</td><td class='num'>{ape}</td>"
            w = " <span class='warn'>empate en el corte de K</span>" if r["empate_corte_K"] else ""
            o.append(f"<tr>{row}<td>{e(r['regla'])}{w}</td></tr>")
        o.append("</table><table><tr><th>#</th><th>Previa</th><th class='num'>Sim.</th><th class='num'>Valor</th>"
                 + "".join(f"<th>{e(v)}</th>" for v in variantes) + "<th>Motivo</th></tr>")
        for d in det[:top]:
            m = "".join(f"<td>{'<span class=in>✓</span>' if d['en_' + v] else '<span class=out>·</span>'}</td>" for v in variantes)
            w = " <span class='warn'>empate</span>" if d["empate_corte_K"] else ""
            o.append(f"<tr><td>{d['rank_sim']}</td><td>{e(d['previa'])}</td><td class='num'>{d['similitud']:.3f}</td>"
                     f"<td class='num'>{_fmt(d['valor_original'])}</td>{m}<td>{e(d['motivo'])}{w}</td></tr>")
        if len(det) > top:
            o.append(f"<tr><td colspan='99' class='txt'>… {len(det) - top} previas más en el CSV de detalle</td></tr>")
        o.append("</table></div>")
    o.append("</body></html>")
    path.write_text("\n".join(o), encoding="utf-8")
