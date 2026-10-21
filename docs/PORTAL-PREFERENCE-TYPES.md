# Portal color preference representation

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

This decision adds documentation only. Production code, tests, dependencies,
configuration, and appearance behavior remain unchanged. Contrast evaluation
belongs to Phase 34.
