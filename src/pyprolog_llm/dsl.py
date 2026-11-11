"""DSL pythónico: T.padre('tom', T.X) -> Compound('padre', (Atom('tom'), Variable('X')))."""
from .engine import coerce
from .terms import Compound, Variable


class _Builder:
    """Atributos en Mayúscula -> Variable; en minúscula -> constructor de Compound."""

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        if name[0].isupper() or name[0] == "_":
            return Variable(name)

        def make(*args):
            return Compound(name, tuple(coerce(a) for a in args))
        return make

    def var(self, name: str) -> Variable:
        return Variable(name)

    def term(self, functor: str, *args) -> Compound:
        return Compound(functor, tuple(coerce(a) for a in args))


T = _Builder()
