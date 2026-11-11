"""Línea de comandos: pyprolog-llm {consult,validar,reporte,demo}."""
from __future__ import annotations

import argparse
import math
import sys
import time


def _consult(a):
    from .engine import Engine
    e = Engine()
    for f in a.archivos:
        print(f"% {f}: {e.consult_file(f)} cláusulas")
    if a.query:
        n = 0
        for sol in e.query(a.query):
            print(sol or "true.")
            n += 1
            if a.max and n >= a.max:
                break
        if n == 0:
            print("false.")


def _validar(a):
    from .io import cargar_directorio, validar
    t0 = time.time()
    ce, _, ref = cargar_directorio(a.datos, a.min_k, a.k)
    print(f"Hechos: {len(ce.e.clauses):,} | carga {time.time() - t0:.1f}s")
    t0 = time.time()
    res = validar(ce, ref, a.tol, a.max_consultas)
    tot = sum(r["ok"] for r in res.values()), sum(r["total"] for r in res.values())
    print(f"\nValidación ({time.time() - t0:.1f}s):")
    for v, r in res.items():
        print(f"  {v:<8} {r['ok']:>5}/{r['total']}  {'OK' if r['ok'] == r['total'] else 'REVISAR'}")
        for q, g, x in r["empates"]:
            print(f"     ~ {q}: empate en el corte de K (prolog={g}, referencia={x})")
        for q, g, x in r["fallos"][:10]:
            print(f"     x {q}: prolog={g} referencia={x}")
    print(f"  TOTAL    {tot[0]}/{tot[1]} ({tot[0] / max(tot[1], 1) * 100:.1f}%)")
    return 0 if tot[0] == tot[1] else 1


def _reporte(a):
    from .io import cargar_directorio
    from .report import generar_reporte, mdape_por_variante
    ce, info, ref = cargar_directorio(a.datos, a.min_k, a.k)
    consultas = [r["id"] for r in ref] if ref else sorted({p.split("|")[0] for p in []})
    if not consultas:
        print("No hay consultas (ref_cohortes.csv vacío o ausente).")
        return 1
    tr = math.expm1 if a.log1p else (lambda x: x)
    variantes = a.variantes.split(",")
    t0 = time.time()
    R = generar_reporte(ce, consultas, a.salida or f"{a.datos}/reporte", variantes, info, tr, a.n_html)
    print(f"Reporte: {len(R):,} filas de resumen ({time.time() - t0:.1f}s) → {a.salida or a.datos + '/reporte'}")
    m = mdape_por_variante(R)
    if m:
        print("\nMdAPE por variante (ilustrativo):")
        for v in variantes:
            if v in m:
                print(f"  {v:<8} {m[v]:.1f}")


def _ontologia(a):
    from .ontology import Ontologia
    pref = dict(x.split("=", 1) for x in (a.prefijo or []))
    o = Ontologia(prefijos=pref)
    n = 0
    for f in a.archivos:
        n += o.cargar_archivo(f)
    if a.sparql:
        n += o.cargar_sparql(a.sparql)
    print(f"% {n:,} triples cargados")
    if a.verificar:
        for linea in open(a.verificar, encoding="utf-8"):
            partes = [x.strip() for x in linea.split("\t") if x.strip()] or None
            if partes and len(partes) == 3:
                v = o.verificar(*partes)
                print(f"{v.estado:<13} {' '.join(partes)}")
                for x in v.explicacion:
                    print(f"              · {x}")
    if a.validar:
        vs = o.validar()
        print(f"\nSHACL: {len(vs)} violaciones")
        for v in vs[:200]:
            print(f"  {v.foco:<30} {v.forma:<25} {v.mensaje}")
        return 1 if vs else 0
    if a.query:
        for sol in o.consultar(a.query)[: a.max]:
            print(sol or "true.")


def _demo(_):
    from .engine import Engine
    e = Engine()
    e.consult("""
        es_un(perro, mamifero). es_un(gato, mamifero). es_un(mamifero, animal). es_un(salmon, pez). es_un(pez, animal).
        puede(pez, nadar). tiene(mamifero, sangre_caliente).
        subclase(X, Y) :- es_un(X, Y).
        subclase(X, Z) :- es_un(X, Y), subclase(Y, Z).
        posee(X, P) :- puede(X, P).
        posee(X, P) :- tiene(X, P).
        posee(X, P) :- es_un(X, Y), posee(Y, P).
    """)
    for q in ["subclase(perro, animal)", "subclase(perro, pez)", "posee(salmon, nadar)", "posee(salmon, sangre_caliente)"]:
        print(f"?- {q}.  {'true' if e.ask(q) else 'false'}")
    print("?- subclase(X, animal).", [str(s["X"]) for s in e.query("subclase(X, animal)")])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pyprolog-llm", description="Programación lógica explicable para contexto semántico")
    sp = ap.add_subparsers(dest="cmd", required=True)

    c = sp.add_parser("consult", help="cargar archivos .pl y ejecutar una consulta")
    c.add_argument("archivos", nargs="+")
    c.add_argument("-q", "--query")
    c.add_argument("--max", type=int, default=50)
    c.set_defaults(fn=_consult)

    for name, fn, hlp in (("validar", _validar, "validar cohortes contra ref_cohortes.csv"),
                          ("reporte", _reporte, "reporte de trazabilidad CSV + HTML")):
        p = sp.add_parser(name, help=hlp)
        p.add_argument("--datos", required=True, help="carpeta con hechos.csv, similar.csv, ref_cohortes.csv")
        p.add_argument("--min-k", type=int, default=5)
        p.add_argument("--k", type=int, default=10)
        p.set_defaults(fn=fn)
        if name == "validar":
            p.add_argument("--tol", type=float, default=1e-4)
            p.add_argument("--max-consultas", type=int, default=None)
        else:
            p.add_argument("--salida", default=None)
            p.add_argument("--variantes", default="A,B0.3,B0.6,BH0.6,K")
            p.add_argument("--n-html", type=int, default=50)
            p.add_argument("--log1p", action="store_true", help="los valores están en log1p: reportar en escala original")

    o = sp.add_parser("ontologia", help="cargar RDF/OWL/SHACL, verificar afirmaciones y validar formas")
    o.add_argument("archivos", nargs="*", help=".ttl/.owl/.rdf/.jsonld (requiere rdflib) o .nt")
    o.add_argument("--sparql", help="endpoint SPARQL 1.1 del que cargar ?s ?p ?o")
    o.add_argument("--prefijo", action="append", help="pre=http://...  (repetible)")
    o.add_argument("--verificar", help="archivo TSV con afirmaciones: sujeto<TAB>predicado<TAB>objeto")
    o.add_argument("--validar", action="store_true", help="evaluar formas SHACL")
    o.add_argument("-q", "--query", help="consulta Prolog, p. ej. \"instancia(X, 'ex:Servicio')\"")
    o.add_argument("--max", type=int, default=50)
    o.set_defaults(fn=_ontologia)

    d = sp.add_parser("demo", help="demo de taxonomía")
    d.set_defaults(fn=_demo)

    a = ap.parse_args(argv)
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
