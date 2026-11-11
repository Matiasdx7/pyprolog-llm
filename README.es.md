# pyprolog-llm

[English](README.md) | **Español**

Motor de **programación lógica (Prolog) en Python puro**, sin dependencias, para resolver problemas de **contexto semántico explicable**. Combina similitudes de embeddings (BETO, sentence-transformers, OpenAI…) con reglas lógicas auditables.

Nació en la tesis MII USACH *Precios de referencia en compras públicas*. Ahí reprodujo exactamente las cohortes BETO del Capítulo VI: **1.598 de 1.600 coincidencias, y los 2 casos restantes son empates en el vecino k = 10**. Además permite explicar cada precio de referencia.

## Instalación

```bash
cd pyprolog-llm
pip install -e .            # o: pip install -e ".[dev]" para tests
pytest -q
```

Requiere Python 3.10 o superior. **No tiene dependencias**: no necesita numpy ni pandas.

## 1. Motor lógico

```python
from pyprolog_llm import Engine, T

e = Engine()
e.consult("""
    es_un(perro, mamifero).  es_un(mamifero, animal).  puede(pez, nadar).
    subclase(X, Y) :- es_un(X, Y).
    subclase(X, Z) :- es_un(X, Y), subclase(Y, Z).
""")
e.ask("subclase(perro, animal)")          # True
e.query_all("subclase(X, animal)")        # [{'X': perro}, {'X': mamifero}]
e.query_all(T.subclase(T.X, "animal"))    # misma consulta, escrita con el DSL de Python
```

**Qué incluye:**
- **Sintaxis:** hechos, reglas, recursión, listas `[a, b]`, números, `_` y comentarios `%`.
- **Predicados internos:** `= \= == < =< > >= =:= is`, `\+`/`not`, `findall/3`, `length/2`, `member/2`, `sum/2`, `min_list/2`, `max_list/2`, `median/2`, `top_k/3` y `print/1`.
- **Índices:** por predicado, por primer argumento y por los dos primeros argumentos en hechos sin variables. En el caso de la tesis carga 400 mil hechos en unos 2 s.
- **Predicados propios desde Python:** con `e.register_builtin("nombre", aridad, fn)`.

## 2. Cohortes semánticas explicables

`CohortEngine` sirve para cualquier dominio donde haya que estimar un valor a partir de **ítems previos, del mismo grupo y semánticamente similares**:

```python
from pyprolog_llm import CohortEngine

ce = CohortEngine(min_k=5, k=10)
ce.cargar_items(ids, grupos, fechas, valores, atributos)   # valores: p. ej. log1p(precio)
ce.cargar_similitudes(pares)                               # iterable de (consulta, previa, coseno)

ce.estimar("q1", "B0.6")       # Estimacion(valor, n, fuente='b(0.6)' | 'fallback_a')
ce.miembros("q1", "B0.6")      # ids de la cohorte
ce.explicar("q1")              # previas con similitud y pertenencia por variante
ce.empate_en_corte("q1")       # True solo si el empate en el vecino k cambia la mediana
```

| Variante | Regla |
|---|---|
| `A` | Previas del mismo grupo (solo historia anterior) |
| `B<τ>` | `A` ∩ similitud ≥ τ |
| `BH<τ>` | `B<τ>` ∩ misma firma de atributos (o la consulta no tiene atributos) |
| `K` | Las k previas más similares |
| respaldo | Si la cohorte tiene menos de `min_k` previas → se usa `A` |

Las reglas están escritas en Prolog en `cohorts.REGLAS`. Se pueden extender sin tocar el código, con `CohortEngine(reglas_extra="...")`.

## 3. Reportes de trazabilidad

```python
import math
from pyprolog_llm.report import generar_reporte, mdape_por_variante
R = generar_reporte(ce, consultas, "reporte/", ("A", "B0.6", "BH0.6", "K"),
                    info={q: {"real": lp_real, "texto": "...", "grupo": "781118"}},
                    transform=math.expm1)          # para pasar de log1p a pesos
mdape_por_variante(R)
```

Genera `trazabilidad.html` (fichas con buscador), `trazabilidad_resumen.csv` y `trazabilidad_detalle.csv`.

## 4. Ontologías (RDF / OWL / SHACL)

`Ontologia` carga una ontología gobernada y razona sobre ella. Puede leerla de un archivo Turtle/OWL (con `rdflib`), de N-Triples (sin dependencias) o de cualquier endpoint SPARQL 1.1: Neptune, Context Ontology Accelerator, Fuseki, etc.

```python
from pyprolog_llm import Ontologia
o = Ontologia(prefijos={"ex": "http://example.org/compras#"})
o.cargar_archivo("dominio.ttl")
o.verificar("ex:oc1", "rdf:type", "ex:Bien")   # soportada | contradicha | sin_respaldo, con explicación
o.validar()                                     # violaciones SHACL
```

Usa un subconjunto de RDFS/OWL: subClassOf/subPropertyOf (transitivas), domain/range, inverseOf, TransitiveProperty, FunctionalProperty y disjointWith. De SHACL soporta minCount, maxCount, class, in, minInclusive, maxInclusive y datatype. Se combina con `CohortEngine` si ambos usan el mismo motor (`engine=ce.e`).

## 5. Línea de comandos

```bash
pyprolog-llm demo
pyprolog-llm consult reglas.pl -q "subclase(X, animal)"
pyprolog-llm validar --datos data/pyprolog                 # compara contra ref_cohortes.csv
pyprolog-llm reporte --datos data/pyprolog --log1p --n-html 200
```

`--datos` espera el formato que genera `export_pyprolog_oe3.py`: `hechos.csv` (id, clase, t_ns, lp, atr[, texto]), `similar.csv` (q, p, s) y `ref_cohortes.csv`.

## Estructura

```
src/pyprolog_llm/
  terms.py    términos, sustitución, unificación (Robinson + occurs-check)
  parser.py   sintaxis Prolog → cláusulas
  engine.py   resolución SLD, índices y predicados internos
  dsl.py      T.pred(...) / T.Variable
  cohorts.py  CohortEngine + reglas A/B/BH/K
  report.py   trazabilidad CSV + HTML
  io.py       carga de CSV y validación contra referencia
  cli.py      pyprolog-llm {demo, consult, validar, reporte}
tests/        pytest
```

## Limitaciones

- **Rendimiento:** es un intérprete en Python, unos 20 ms por consulta y variante en clases grandes. Sirve para validar, explicar y auditar, no para recalcular cientos de miles de filas.
- **Funciones de Prolog que no incluye:** cut (`!`), `assert`/`retract` en tiempo de ejecución y los operadores definidos por el usuario.
- **Empates en `K`:** se rompen por el orden en que se cargan los datos. Usa `empate_en_corte()` para detectarlos.

## Licencia

MIT
