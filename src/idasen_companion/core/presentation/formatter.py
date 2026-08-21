"""The ``Formatter`` facade and the context it holds.

This module records the design's § 14 call-site decision — the choice
between threading a presentation context explicitly through every
formatter's signature, and bundling it behind a small facade object — as
committed source, because ``.planning/`` is gitignored on this project and
would take the reasoning with it if it lived there instead.

**The chosen shape.** A single ``Formatter`` facade, built once from a
``PresentationContext``, so a call site reads ``Formatter(ctx).height(m)``
rather than ``fmt_height(m, ctx)``. The context is held by the facade
instead of being threaded through roughly twenty formatter signatures and
every ``gui/util.py`` wrapper around them.

**Why.** Two sources reached the same answer independently. The design
document says that for that many helpers it would probably choose the
facade form. Separately, and before that document was written, this
project's own backlog already proposed a small immutable object built from
language and unit, owned by the GUI's shared context, exposing the
vocabulary as methods. Two routes, one answer.

**The rejected alternative, and its argument.** Passing the context
explicitly at every call site — a plain function taking the value and the
context as arguments — is transparent, trivially testable, and carries no
object lifecycle: nothing to construct, nothing to hold onto past one
call. It was rejected on noise, not on merit: the same context argument
would repeat, unchanged, at every one of roughly twenty formatters times
every call site, plus every thin wrapper in ``gui/util.py`` that exists
only to thread it through. A parameter that is identical at every call is
a parameter worth binding once instead of repeating everywhere.

**What this facade is not.** There is still exactly one ``Formatter``
implementation — the polymorphism lives entirely in its collaborators, the
``LocaleFormatter`` and ``Translator`` the context carries. That is the
distinction from the per-surface renderer set this project already
rejected: a Qt renderer and a headless renderer each reimplementing the
same formatting policy. Here the policy is written once, in this facade's
methods, and only the two small capabilities beneath it vary.

**What this does not settle.** ``gui/widgets.py``'s paint method imports a
height formatter directly because the widget it paints has no context to
reach for. Neither this shape nor the rejected one solves that on its own;
it is PRES-06's problem, not this plan's.
"""

from __future__ import annotations

from dataclasses import dataclass

from .protocols import LocaleFormatter, Translator


@dataclass(frozen=True)
class PresentationContext:
    """The capability pair a :class:`Formatter` renders through.

    Holds exactly the two protocol instances a surface supplies — a
    locale-rendering backend and a message-translating backend — and
    nothing else. Frozen because it is built once per surface and handed
    to every ``Formatter`` that surface constructs; nothing here changes
    over the context's lifetime.
    """

    locale: LocaleFormatter
    translator: Translator


class Formatter:
    """Renders values and messages through an injected presentation context.

    Holds a :class:`PresentationContext` and nothing else. This class
    deliberately has **no formatting methods yet** — ``height``,
    ``duration``, ``status`` and the rest arrive in Phases 13, 14 and 15,
    one at a time, as each existing formatter moves onto this facade. Do
    not "finish" this class by moving a formatter here early: this plan's
    own constraints forbid it, and the phases after this one are where
    that work is planned, tested and translated.

    See the module docstring for the recorded § 14 decision — this facade
    over an explicit context argument at every call site — and the
    rejected alternative's own argument.
    """

    def __init__(self, context: PresentationContext) -> None:
        self._context = context

    @property
    def context(self) -> PresentationContext:
        """The context this facade was built from."""
        return self._context
