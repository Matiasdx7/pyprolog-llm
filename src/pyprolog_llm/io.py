"""Carga de datos desde CSV (sin pandas) — formato de export_pyprolog_oe3.py."""
from __future__ import annotations

import csv
from pathlib import Path

from .cohorts import CohortEngine


def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def cargar_directorio(d, min_k: int = 5, k: int = 10, col_grupo: str = "clase", col_tiempo: str = "t_ns",
                      col_valor: str = "lp") -> tuple[CohortEngine, dict, list[dict]]:
    """
    Lee <d>/hechos.csv, <d>/similar.csv y (opcional) <d>/ref_cohortes.csv.

    hechos.csv:   id, clase, t_ns, lp, atr[, split, texto]
    similar.csv:  q, p, s
    Devuelve (CohortEngine, info por id, filas de referencia).
    """
    d = Path(d)
    ce = CohortEngine(min_k=min_k, k=k)
    info = {}
    ids, gs, ts, vs, ats = [], [], [], [], []
    for r in _rows(d / "hechos.csv"):
        ids.append(r["id"]); gs.append(r[col_grupo]); ts.append(int(float(r[col_tiempo])))
        vs.append(float(r[col_valor])); ats.append(r.get("atr", "") or "")
        info[r["id"]] = {"grupo": r[col_grupo], "atr": r.get("atr", ""), "texto": r.get("texto", ""),
                         "real": float(r[col_valor])}
    ce.cargar_items(ids, gs, ts, vs, ats)
    ce.cargar_similitudes((r["q"], r["p"], float(r["s"])) for r in _rows(d / "similar.csv"))
    ref = list(_rows(d / "ref_cohortes.csv")) if (d / "ref_cohortes.csv").exists() else []
    return ce, info, ref


def validar(ce: CohortEngine, ref: list[dict], tol: float = 1e-4, max_consultas: int | None = None) -> dict:
    """Compara CohortEngine.estimar() contra valores de referencia por variante."""
    if not ref:
        return {}
    variantes = [c for c in ref[0] if c != "id" and not c.endswith("_n")]
    res = {v: {"ok": 0, "total": 0, "empates": [], "fallos": []} for v in variantes}
    for r in ref[:max_consultas]:
        q = r["id"]
        for v in variantes:
            exp = r[v]
            exp = None if exp in ("", "nan", "NaN") else float(exp)
            got = ce.estimar(q, v)
            ok = (got is None and exp is None) or (got is not None and exp is not None and abs(got.valor - exp) < tol)
            res[v]["total"] += 1
            if ok:
                res[v]["ok"] += 1
            elif v.upper() == "K" and ce.empate_en_corte(q, solo_si_cambia=False):
                res[v]["ok"] += 1
                res[v]["empates"].append((q, None if got is None else got.valor, exp))
            else:
                res[v]["fallos"].append((q, None if got is None else got.valor, exp))
    return res
