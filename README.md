# pyprolog-llm

**English** | [Español](README.es.md)

A **pure-Python Prolog engine** for **explainable semantic context** problems. It has no dependencies. It combines embedding similarities (BETO, sentence-transformers, OpenAI, …) with logic rules you can audit.

It started in a master's thesis (USACH, Chile) on *reference prices in public procurement*. There it reproduced a numpy pipeline of semantic cohorts: **1,598 of 1,600 exact matches**, and the other 2 are tie-breaks at the k-th neighbour. It also explains every estimated price.

## Installation

```bash
pip install pyprolog-llm          # once published
# or, from source:
pip install -e ".[dev]" && pytest -q
```

Requires Python 3.10+. **No runtime dependencies**: you don't need numpy or pandas.

## 1. Logic engine

```python
from pyprolog_llm import Engine, T

e = Engine()
e.consult("""
    is_a(dog, mammal).  is_a(mammal, animal).  can(fish, swim).
    subclass(X, Y) :- is_a(X, Y).
    subclass(X, Z) :- is_a(X, Y), subclass(Y, Z).
""")
e.ask("subclass(dog, animal)")           # True
e.query_all("subclass(X, animal)")       # [{'X': dog}, {'X': mammal}]
e.query_all(T.subclass(T.X, "animal"))   # same query, written with the Python DSL
```

**What it includes:**
- **Syntax:** facts, rules, recursion, lists `[a, b]`, numbers, `_` and `%` comments.
- **Built-in predicates:** `= \= == < =< > >= =:= is`, `\+`/`not`, `findall/3`, `length/2`, `member/2`, `sum/2`, `min_list/2`, `max_list/2`, `median/2`, `top_k/3` and `print/1`.
- **Indexing:** by predicate, by first argument, and by the first two arguments for ground facts. It loads about 400k facts in roughly 2 s.
- **Your own predicates from Python:** with `e.register_builtin("name", arity, fn)`.

## 2. Explainable semantic cohorts

`CohortEngine` works in any domain where you estimate a value from **earlier, same-group, semantically similar items**:

```python
from pyprolog_llm import CohortEngine

ce = CohortEngine(min_k=5, k=10)
ce.cargar_items(ids, groups, times, values, attributes)   # values: e.g. log1p(price)
ce.cargar_similitudes(pairs)                              # iterable of (query, prior, cosine)

ce.estimar("q1", "B0.6")      # Estimacion(valor, n, fuente='b(0.6)' | 'fallback_a')
ce.miembros("q1", "B0.6")     # ids in the cohort
ce.explicar("q1")             # priors with similarity and membership per variant
ce.empate_en_corte("q1")      # True only if a tie at neighbour k changes the median
```

| Variant | Rule |
|---|---|
| `A` | Earlier items of the same group (past history only, no leakage) |
| `B<τ>` | `A` ∩ similarity ≥ τ |
| `BH<τ>` | `B<τ>` ∩ same attribute signature (or the query has none) |
| `K` | The k most similar earlier items |
| fallback | If a cohort has fewer than `min_k` members, `A` is used |

The rules are written in Prolog in `cohorts.REGLAS`. You can extend them without touching the code, with `CohortEngine(reglas_extra="...")`.

> **Note on naming:** the cohort API keeps Spanish method names (`cargar_items`, `estimar`, `explicar`, …) because it comes from the thesis. English aliases are planned for 0.2.0.

## 3. Traceability reports

```python
import math
from pyprolog_llm.report import generar_reporte, mdape_por_variante
R = generar_reporte(ce, queries, "report/", ("A", "B0.6", "BH0.6", "K"),
                    info={q: {"real": true_log_value, "texto": "...", "grupo": "781118"}},
                    transform=math.expm1)        # from log1p back to the original scale
mdape_por_variante(R)
```

It writes `trazabilidad.html` (searchable cards), `trazabilidad_resumen.csv` and `trazabilidad_detalle.csv`.

## 4. Ontologies (RDF / OWL / SHACL)

`Ontologia` loads a governed ontology and reasons over it. Sources can be a Turtle/OWL file (with `rdflib`), N-Triples (no dependencies) or any SPARQL 1.1 endpoint: Amazon Neptune, [Context Ontology Accelerator](https://aws.github.io/context-ontology-accelerator/), Fuseki, GraphDB, …

```python
from pyprolog_llm import Ontologia

o = Ontologia(prefijos={"ex": "http://example.org/compras#"})
o.cargar_archivo("domain.ttl")                     # pip install "pyprolog-llm[rdf]"
# o.cargar_sparql("https://.../sparql", headers={"Authorization": "Bearer ..."})

o.clases_de("ex:oc1")                              # inherited types (rdfs:subClassOf*)
o.valores("ex:minsal", "ex:contiene")              # inverse + transitive properties

v = o.verificar("ex:oc1", "rdf:type", "ex:Bien")   # e.g. a triple extracted from an LLM answer
v.estado        # 'soportada' | 'contradicha' | 'sin_respaldo'
v.explicacion   # ['ex:oc1 es instancia de ex:Servicio', 'ex:Bien y ex:Servicio son disjuntas (owl:disjointWith)']

for viol in o.validar():                           # SHACL shapes in the same graph
    print(viol.foco, viol.mensaje)
```

**Supported semantics:** `rdfs:subClassOf`/`subPropertyOf` (transitive), `rdfs:domain`/`range`, `owl:inverseOf`, `owl:TransitiveProperty`, `owl:FunctionalProperty`, `owl:disjointWith`. **SHACL:** `sh:targetClass` + `sh:property` with `minCount`, `maxCount`, `class`, `in`, `minInclusive`, `maxInclusive` and `datatype`. Under the open-world assumption, anything that cannot be derived or contradicted is reported as `sin_respaldo` ("unsupported"), not as false.

**Ontology + cohorts.** Pass the same engine (`Ontologia(engine=ce.e)`) and write rules that mix both. For example, a cohort that also requires the same unit of charge declared in the ontology:

```prolog
en_cohorte(bo(Tau), Q, P, V) :- en_cohorte(b(Tau), Q, P, V), tp('ex:unidadCobro', Q, U), tp('ex:unidadCobro', P, U).
```

See `examples/ontologia_y_cohortes.py`.

## 5. Command line

```bash
pyprolog-llm demo
pyprolog-llm consult rules.pl -q "subclass(X, animal)"
pyprolog-llm validar --datos data/pyprolog                 # compare against ref_cohortes.csv
pyprolog-llm reporte --datos data/pyprolog --log1p --n-html 200
pyprolog-llm ontologia examples/compras.nt --prefijo ex=http://example.org/compras# \
    --verificar examples/afirmaciones_llm.tsv --validar
```

`--datos` expects a folder with `hechos.csv` (id, clase, t_ns, lp, atr[, texto]), `similar.csv` (q, p, s) and `ref_cohortes.csv`.

## Project layout

```
src/pyprolog_llm/
  terms.py    terms, substitution, unification (Robinson + occurs-check)
  parser.py   Prolog syntax → clauses
  engine.py   SLD resolution, indexing and built-ins
  dsl.py      T.pred(...) / T.Variable
  cohorts.py  CohortEngine + A/B/BH/K rules
  report.py   CSV + HTML traceability
  io.py       CSV loading and validation against a reference
  ontology.py RDF/OWL/SHACL loading, reasoning, claim checking, SHACL validation
  cli.py      pyprolog-llm {demo, consult, validar, reporte}
tests/        pytest
```

## Limitations

- **Performance:** it is an interpreter in Python, about 20 ms per query and variant on large groups. It is meant for validating, explaining and auditing, not for recomputing hundreds of thousands of rows.
- **Ontology reasoning** is a practical RDFS/OWL subset, not a full OWL 2 DL reasoner. Cycles in `rdfs:subClassOf` are detected and reported, but not supported.
- **Prolog features not included:** cut (`!`), runtime `assert`/`retract` and user-defined operators.
- **Ties in `K`:** they are broken by the order in which data is loaded. Use `empate_en_corte()` to detect them.

## License

MIT
