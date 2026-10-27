# Portal color and contrast preference representations

This document records separate color (Phase 33) and contrast (Phase 34)
representation decisions.

**Decision: retain the validated raw `int | None` boundary.** Phase 33 evaluated
the current color path at baseline
`b0e5349986df5d51fab94b4ae3f021fbf889ff44`. A plain `Enum` would currently be an
unused abstraction: no production consumer retains or acts on the color
preference. This follows the I15 adapter guidance in
[the semantic types assessment](SEMANTIC-TYPES-ASSESSMENT.md): validate external
primitive codes first; introduce an internal vocabulary when a real consumer
needs it.

## Current producer and consumer

In `src/idasen_companion/gui/appearance_portal.py`, `_read_one` unwraps one
`QDBusVariant` layer, also accepts bare scalars, rejects `bool` and non-integer
payloads, and accepts only the known color codes `0`, `1`, and `2` from
`_VALID_VALUES["color-scheme"]`. It returns the original integer, without
coercion. Missing service/key replies, empty replies, invalid payloads, and
unknown codes return `None`.

`read_appearance_preferences()` stores that result in
`AppearancePreferences.color_scheme: int | None`. Its successful diagnostic
uses `color-scheme={color_scheme!r}`, retaining the raw repr output; the
all-absent result keeps the existing debug diagnostic. Neither absence nor a
failed read acquires a new fallback policy.

The sole production call is the expression statement
`appearance_portal.read_appearance_preferences()` in
`src/idasen_companion/gui/main.py:102`, after the single-instance gate. Its
returned record is discarded. There is no production field consumer or
portal-to-Qt conversion. The existing palette/theme path does not consume this
record. Naming an internal enum now would add a conversion and representation
with no internal user; the existing validation already constrains the raw
boundary.

## Mapping required by a future consumer

Portal and Qt integers have different meanings. A future conversion must use
this semantic table:

| Portal code | Portal meaning | Qt member | Qt value |
| --- | --- | --- | --- |
| 0 | no preference | `Qt.ColorScheme.Unknown` | 0 |
| 1 | dark | `Qt.ColorScheme.Dark` | 2 |
| 2 | light | `Qt.ColorScheme.Light` | 1 |

Direct construction of the Qt enum from the portal integer is semantically
wrong: it exchanges dark and light. `None` remains absence, distinct from the
valid portal code `0` for no preference.

Re-evaluate this decision when a production consumer retains or acts on the
color preference and needs an internal vocabulary or Qt conversion. Decode
only after the existing validation, preserve the current `None` and diagnostic
contracts, and map by meaning using the table above.

## Verification and scope

The existing `tests/test_appearance_portal.py` covers bare and wrapped values,
bounded reads, invalid types including booleans, unknown codes, missing/empty
replies, independent key validity, diagnostic logging, and unchanged theme
tokens. Phase 33 runs that retained file freshly offscreen on a private session
bus; disposable AST and receipt-integrity audits live under `/tmp`.

These representation decisions add documentation only. Production code, tests,
dependencies, configuration, and appearance behavior remain unchanged.

## Contrast preference decision (Phase 34)

**Decision: retain the validated raw `int | None` contrast boundary.** Phase 34
independently evaluated contrast at baseline
`3a4eab33eb1b41294c9c6517776e87ef7d699bee`. In
`src/idasen_companion/gui/appearance_portal.py`, `_read_one` accepts bare scalar
replies or unwraps one `QDBusVariant` layer, rejects `bool` and non-integer
payloads, and checks `_VALID_VALUES["contrast"] == (0, 1)` before returning the
original integer. Code `0` means normal contrast and code `1` means high
contrast. Code `2` is invalid for contrast even though it is valid for color.
Invalid types, unknown codes, missing/empty replies and failed portal reads
remain `None`; valid `0` remains distinct from absence.

`read_appearance_preferences()` stores the result in
`AppearancePreferences.contrast: int | None` and logs `contrast={contrast!r}`
using raw repr. The all-absent debug diagnostic also remains unchanged. The
independent production reference search again finds the sole read at
`gui/main.py:102`, a discarded expression after the single-instance gate. No
production contrast-field consumer retains or acts on the result; references
to text contrast elsewhere in styling are unrelated to this portal preference.
A plain `Enum` would therefore introduce an unused internal vocabulary and
conversion without helping a current consumer. The validated external integer
already expresses this adapter boundary.

The supported GUI dependency is `PySide6>=6.5` in `pyproject.toml`.
As documented in the semantic assessment's I15 comparison,
`Qt.ContrastPreference` was introduced in Qt 6.10 and is unavailable at the
Qt 6.5 minimum. It cannot be used unconditionally at that floor. A substitute
adapter would also have no current consumer, so neither a native enum nor an
adapter is introduced by this decision. No Qt floor change is selected.

Reconsider contrast when a real production consumer retains or acts on it,
together with an explicit appearance policy and a representation compatible
with the supported Qt floor. Preserve the existing validation, absence and
diagnostic contracts before decoding into any needed internal vocabulary.
The existing high-contrast feature todo remains open: this representation
decision adds no appearance behavior or rendering policy.

Phase 34 freshly runs all 16 existing portal tests offscreen on a private
session bus. The retained cases include normal `0`, high `1` with unchanged
theme tokens, invalid `2`, bare/wrapped decoding, bool/non-integer and unknown
rejection, absence and logging. No test is added, expanded or removed.
