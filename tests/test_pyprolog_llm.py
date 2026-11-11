"""Tests del motor, parser, cohortes y reportes. Ejecutar: pytest -q"""
import math
import random

import pytest

from pyprolog_llm import Atom, CohortEngine, Engine, T, Variable, parse_query, unify
from pyprolog_llm.terms import Compound, Substitution


# ------------------------------------------------------------------ unificación
def test_unify_basico():
    s = unify(Variable("X"), Atom("a"), Substitution())
    assert s.walk(Variable("X")) == Atom("a")
    assert unify(Atom("a"), Atom("b"), Substitution()) is None


def test_unify_compuesto_y_occurs_check():
    X, Y = Variable("X"), Variable("Y")
    s = unify(Compound("f", (X, Atom("b"))), Compound("f", (Atom("a"), Y)), Substitution())
    assert s.walk(X) == Atom("a") and s.walk(Y) == Atom("b")
    assert unify(X, Compound("f", (X,)), Substitution()) is None


# ------------------------------------------------------------------ motor + parser
@pytest.fixture
def familia():
    e = Engine()
    e.consult("""
        padre(tom, bob). padre(tom, liz). padre(bob, ann). madre(ann, jim).
        prog(X, Y) :- padre(X, Y).
        prog(X, Y) :- madre(X, Y).
        anc(X, Y) :- prog(X, Y).
        anc(X, Z) :- prog(X, Y), anc(Y, Z).
        herm(X, Y) :- padre(Z, X), padre(Z, Y), X \\= Y.
        doble(X, Y) :- Y is X * 2.
        huerfano(X) :- padre(_, X), \\+ madre(_, X).
    """)
    return e


def test_recursion(familia):
    assert sorted(str(r["Q"]) for r in familia.query("anc(Q, jim)")) == ["ann", "bob", "tom"]


def test_ask_ground(familia):
    assert familia.ask("anc(tom, jim)")
    assert not familia.ask("anc(jim, tom)")


def test_desigualdad_y_aritmetica(familia):
    assert [str(r["Y"]) for r in familia.query("herm(bob, Y)")] == ["liz"]
    assert familia.query_first("doble(21, Y)") == {"Y": 42}


def test_findall_length_negacion(familia):
    r = familia.query_first("findall(X, padre(tom, X), L), length(L, N)")
    assert r["N"] == 2 and tuple(map(str, r["L"])) == ("bob", "liz")
    assert familia.ask("huerfano(bob)")


def test_dsl_equivale_a_texto(familia):
    assert familia.query_all(T.anc(T.Q, "jim")) == familia.query_all("anc(Q, jim)")


def test_listas_y_agregados():
    e = Engine()
    assert e.query_first("median([3, 1, 2], M)") == {"M": 2.0}
    assert e.query_first("member(X, [a, b]), X \\= a") == {"X": Atom("b")}
    assert e.query_first("sum([1, 2, 3], S)") == {"S": 6}


def test_parse_query_operadores():
    gs = parse_query("p(X), X >= 0.6, X =< 1")
    assert [g.functor for g in gs] == ["p", ">=", "=<"]


def test_builtin_personalizado():
    e = Engine()

    def es_par(args, sub, _):
        if sub.walk(args[0]) % 2 == 0:
            yield sub
    e.register_builtin("es_par", 1, es_par)
    e.consult("n(1). n(2). n(4).")
    assert [r["X"] for r in e.query("n(X), es_par(X)")] == [2, 4]


# ------------------------------------------------------------------ cohortes vs referencia
def _sintetico(n=300, seed=7):
    rnd = random.Random(seed)
    grupos = [rnd.choice(["g1", "g2", "g3"]) for _ in range(n)]
    fechas = rnd.sample(range(n * 10), n)
    valores = [rnd.gauss(10, 1) for _ in range(n)]
    atrs = [rnd.choice(["", "", "500ml", "1l"]) for _ in range(n)]
    return grupos, fechas, valores, atrs, rnd


def _ref(q, grupos, fechas, valores, atrs, sim, var, min_k=5, k=10):
    pool = [j for j in range(len(grupos)) if grupos[j] == grupos[q] and fechas[j] < fechas[q]]
    med = lambda xs: sorted(xs)[len(xs) // 2] if len(xs) % 2 else sum(sorted(xs)[len(xs) // 2 - 1:len(xs) // 2 + 1]) / 2
    a = [valores[j] for j in pool]
    if var == "A":
        sel = a
    elif var == "K":
        sel = [valores[j] for j in sorted(pool, key=lambda j: -sim[(q, j)])[:k]]
    elif var.startswith("BH"):
        t = float(var[2:])
        sel = [valores[j] for j in pool if sim[(q, j)] >= t and (atrs[q] == "" or atrs[j] == atrs[q])]
    else:
        t = float(var[1:])
        sel = [valores[j] for j in pool if sim[(q, j)] >= t]
    if var != "A" and len(sel) < min_k:
        sel = a
    return med(sel) if sel else None


def test_cohortes_equivalen_a_referencia():
    grupos, fechas, valores, atrs, rnd = _sintetico()
    n = len(grupos)
    consultas = sorted(range(n), key=lambda i: -fechas[i])[:40]
    sim = {}
    for q in consultas:
        for j in range(n):
            if grupos[j] == grupos[q] and fechas[j] < fechas[q]:
                sim[(q, j)] = round(rnd.random(), 6)
    ce = CohortEngine(min_k=5, k=10)
    ce.cargar_items(range(n), grupos, fechas, valores, atrs)
    ce.cargar_similitudes((q, j, s) for (q, j), s in sim.items())
    for q in consultas:
        for v in ("A", "B0.3", "B0.6", "BH0.6", "K"):
            got = ce.estimar(q, v)
            exp = _ref(q, grupos, fechas, valores, atrs, sim, v)
            assert (got is None) == (exp is None)
            if got:
                assert math.isclose(got.valor, exp, abs_tol=1e-9), (q, v)


def test_respaldo_y_sin_fuga_temporal():
    ce = CohortEngine(min_k=5)
    ce.cargar_items(["p1", "p2", "q", "futuro"], ["g"] * 4, [1, 2, 3, 4], [1.0, 3.0, 99.0, 1000.0])
    ce.cargar_similitudes([("q", "p1", 0.9), ("q", "p2", 0.1), ("q", "futuro", 1.0)])
    e = ce.estimar("q", "B0.6")
    assert e.uso_respaldo and e.n == 2 and e.valor == 2.0      # solo p1, p2 (futuro excluido)
    assert "futuro" not in ce.miembros("q", "A")


def test_empate_solo_si_cambia_mediana():
    ce = CohortEngine(min_k=1, k=2)
    ce.cargar_items(list("abcq"), ["g"] * 4, [1, 2, 3, 9], [5.0, 5.0, 5.0, 0.0])
    ce.cargar_similitudes([("q", "a", 0.9), ("q", "b", 0.5), ("q", "c", 0.5)])
    assert ce.empate_en_corte("q", solo_si_cambia=False)
    assert not ce.empate_en_corte("q")                          # mismos valores: el empate no importa


def test_reporte(tmp_path):
    from pyprolog_llm.report import generar_reporte, mdape_por_variante
    ce = CohortEngine(min_k=1, k=2)
    ce.cargar_items(list("abq"), ["g"] * 3, [1, 2, 3], [math.log1p(100), math.log1p(200), math.log1p(150)])
    ce.cargar_similitudes([("q", "a", 0.9), ("q", "b", 0.7)])
    R = generar_reporte(ce, ["q"], tmp_path, ("A", "B0.8", "K"), {"q": {"real": math.log1p(150)}}, math.expm1)
    assert (tmp_path / "trazabilidad.html").exists() and (tmp_path / "trazabilidad_detalle.csv").exists()
    b = next(r for r in R if r["variante"] == "B0.8")
    assert round(b["valor_ref_original"]) == 100 and b["n_cohorte"] == 1
    assert "B0.8" in mdape_por_variante(R)


# ------------------------------------------------------------------ ontologías
EXO = "http://example.org/compras#"


@pytest.fixture
def onto():
    from pathlib import Path
    from pyprolog_llm import Ontologia
    o = Ontologia(prefijos={"ex": EXO})
    o.cargar_archivo(Path(__file__).parent.parent / "examples" / "compras.nt")
    return o


def test_ontologia_jerarquia_y_rango(onto):
    assert set(onto.clases_de("ex:oc1")) == {"ex:TrasladoPorTramo", "ex:ServicioTransporte", "ex:Servicio", "ex:Producto"}
    assert onto.instancias("ex:Organismo") == ["ex:hospitalX"]


def test_ontologia_transitiva_e_inversa(onto):
    assert set(onto.valores("ex:hospitalX", "ex:parteDe")) == {"ex:ssSur", "ex:minsal"}
    assert set(onto.valores("ex:minsal", "ex:contiene")) == {"ex:ssSur", "ex:hospitalX"}


def test_verificar_afirmaciones(onto):
    assert onto.verificar("ex:oc1", "rdf:type", "ex:Producto").estado == "soportada"
    assert onto.verificar(EXO + "oc1", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", EXO + "Servicio").estado == "soportada"
    assert onto.verificar("ex:oc1", "rdf:type", "ex:Bien").estado == "contradicha"
    assert onto.verificar("ex:oc1", "ex:unidadCobro", "hora").estado == "contradicha"
    assert onto.verificar("ex:oc1", "ex:compradoPor", "ex:ssSur").estado == "sin_respaldo"
    assert len(onto.verificar("ex:oc1", "rdf:type", "ex:Producto").explicacion) == 4


def test_shacl(onto):
    vs = {(v.foco, v.restriccion) for v in onto.validar()}
    assert vs == {("ex:oc2", "min_count"), ("ex:oc2", "menor_que")}


def test_ontologia_comparte_motor_con_cohortes():
    from pyprolog_llm import Ontologia
    ce = CohortEngine(min_k=1, k=2)
    o = Ontologia(prefijos={"ex": EXO}, engine=ce.e)
    ce.e.consult("""
        unidad(Q, U) :- tp('ex:unidadCobro', Q, U).
        en_cohorte(bo(Tau), Q, P, V) :- en_cohorte(b(Tau), Q, P, V), unidad(Q, U), unidad(P, U).
        cohorte_lista(bo(Tau), Q, Ls) :- findall(V, en_cohorte(bo(Tau), Q, _, V), Ls).
    """)
    ce.cargar_items(["ex:p1", "ex:p2", "ex:q"], ["g"] * 3, [1, 2, 3], [10.0, 20.0, 0.0])
    o.cargar_triples([("ex:p1", "ex:unidadCobro", "hora"), ("ex:p2", "ex:unidadCobro", "mes"),
                      ("ex:q", "ex:unidadCobro", "hora")])
    ce.cargar_similitudes([("ex:q", "ex:p1", 0.7), ("ex:q", "ex:p2", 0.9)])
    assert ce.estimar("ex:q", "B0.6").valor == 15.0
    assert ce.e.query_first(T.estimar(T.bo(0.6), "ex:q", T.M, T.N, T.F))["M"] == 10.0
