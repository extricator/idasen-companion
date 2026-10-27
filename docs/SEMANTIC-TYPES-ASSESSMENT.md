# Semantic types across numeric boundaries

One comprehensive assessment of the current core, daemon, desk, GUI and CLI,
reassessed 2026-10-20. This is a representation decision, not an implementation.
Legibility, intent and maintenance justify improvement without needing an existing
bug. The source inventory I01–I21 remains current; the alternatives and decisions
below replace the earlier nominal-tag defaults.

Claim labels distinguish **DOCUMENTED** official API contracts, **LOCALLY PROVED**
fresh bounded experiments or identified current-source behavior, **DESIGN JUDGMENT**
the selected tradeoff, and **UNRESOLVED** limits of the available evidence. Probe
case names refer to the new quick 261020-fkh receipt, not prior experiments.

## Executive recommendation

**DESIGN JUDGMENT:** choose two narrow Qt-free quantity values, `Duration` and
`Length`, whose operators retain their meaning, plus separate operational wall
and monotonic instant values using that same Duration. Keep standard calendar
types, existing Qt geometry/colors, appropriate standard records and enums, and
named primitives at raw config/transport/resource boundaries. This is one design
across all eight families; none is deferred to a later assessment.

| Family / every inventory ID | Selected representation and placement | Enforced guarantee and adapter boundary | Deliberate limit / reason |
| --- | --- | --- | --- |
| Duration/configuration — I04–I08, I11 | Shared `Duration(seconds: int | float)` with unit factories; domain +/−, scalar ×/÷ and same-dimension ratio. Raw config remains int seconds. I08 journal input instead produces a wall timestamp. | Candidate preserves input kind/value; domain operations reject Length; unit conversion happens in factories, existing operation order preserved. Raw seconds/ms/min/µs stay at IO boundaries. | No global positivity, finiteness, range or quantization. Qt timers are not general duration values. Config fields and serialized scalars are not silently replaced by objects. |
| Clocks/civil time — I09, I10, I12; I07 deadline | `WallInstant`, `MonotonicInstant` for operational readings/deadlines; same-clock subtraction → Duration; ±Duration → same clock. Existing datetime/date and validated local schedule strings/minute offsets remain. | Candidate rejects unlike-clock subtraction in both static and runtime checks, preserves raw signed subtraction. Explicit scalar output at wire/calendar boundary. | Constructor cannot discover a mislabeled raw reading; historical transport timestamps stay floats. No source-clock, DST, suspend or time-jump policy change. |
| Length — I01–I03 | Shared `Length` with metre/cm/inch factories and natural length arithmetic; existing HeightUnit resolves display preference. | Midpoint/distance/tolerance remain typed expressions; Length/Length → float ratio; domain operations reject Duration. Convert once entering/leaving desk/config/display/wire or pixel mapping. | No new physical bounds, affine-height distinction, range/finiteness policy, or promise that movement succeeded. Scalar extraction remains explicit at adapters. |
| Ratios — I13 | Named float ratio/share/blend locally; existing clamp only at existing rail boundary. | Preserve actual signed/history quotient and formatting behavior. Quantity division produces dimensionless float. | No general 0–1 invariant. Decimal/Fraction express different numeric contracts, not boundedness. A bounded value is conditional only after existing clamping. |
| Qt values — I14 | Existing QPointF/QSizeF/QRectF/QColor and integer variants, GUI only; named logical/device/DPR scalars at scale conversion. | Native position/extent/rectangle/color contracts; explicit scale, round and RTL mapping. | Qt value type does not encode coordinate space or metres. Current 6.11.2 probes do not prove Python bindings at the 6.5 floor. No Qt in shared/headless quantities. |
| Categories — I15; I21 metadata | Plain Enum for newly named internal portal preference families; existing StrEnum/Qt enums retained; validated primitive external codes; Literal where useful internally; transport Annotated retained. | Explicit decoder precedes enum; map portal → Qt by meaning, not integer. Literal is static-only; Annotated requires a consumer. | No new appearance behavior. Unknown/bool/None policies remain; open historical state/response codes must not become closed inadvertently. IntEnum is conditional when integer interop is explicitly needed. |
| Resources/IDs — I16–I18 | Existing SleepInhibitor owns fd lifetime; named int fd/index/UID/PID/notification ID/generation/count/limit/version. | Actual index→fd selection, spare cleanup and idempotent release; fd0 valid, None absent. Existing limits/formatting/schema guards remain. | A tag does not own or close. File/Qt wrappers change lifetime or dependencies; no universal numeric unit fits identity. |
| Records — I19–I21 | Preserve raw scalar DailyStatRow/TransitionRow NamedTuples, LogEntry TypedDict and wire aliases; existing config/events/DurationParts dataclasses. Add GUI-local DailyChartRow NamedTuple with named sit/stand roles. | Tuple APIs/order for decoded DTOs; dict shape for logs. Quantity-bearing domain/chart fields require explicit scalar encoding if serialized. | Same-typed fields can still swap. Do not annotate raw float DTO members as objects without conversion, or claim quantity members serialize automatically because the outer record is a tuple. |

The rule for new boundaries is consistent: use a quantity when meaning should
survive arithmetic, an instant when clock origin constrains operations, a record
when adjacent values have distinct roles, and a native framework/resource owner
for its own responsibility. Primitive scalars remain intentional where they are
the actual storage/API contract or a confined calculation. There is no universal
wrapper, metadata annotation or unit enum that supplies all these capabilities.

## Complete alternatives comparison

**ADMIT** means fit for the stated use; **REJECT** means unsuitable for that use,
not universally useless; **CONDITIONAL** states the condition for a credible
alternative. The selected custom values are bounded designs demonstrated by the
fresh fixtures, not an installed quantity framework or performance claim.

### Duration and integer configuration
<!-- family: duration -->

| Alternative | Capability and evidence | Disposition for I04–I08/I11 |
| --- | --- | --- |
| `datetime.timedelta` | **DOCUMENTED:** unified unit constructor, signed/zero normalized values, comparison, addition/subtraction, scalar scaling and duration ratio. Resolution is microseconds with half-even rounding of fractional microseconds, finite days range; `.seconds` is a normalized component, not total seconds, and total_seconds can lose precision over long spans. [Python 3.11 timedelta](https://docs.python.org/3.11/library/datetime.html#timedelta-objects) | **CONDITIONAL** for a deliberately microsecond-bounded/calendar duration; **REJECT** as universal replacement here. Signed values are supported, so negativity is not the objection. Fresh precision/range and jump-threshold counterexamples below are decisive. |
| Canonical float-only `Duration` | **DESIGN JUDGMENT:** straightforward shared seconds payload, with unit factories and typed operators; can preserve incoming floats without rounding. **LOCALLY PROVED:** a forced float conversion loses integer 2**53+1 and raises for 10**400. | **REJECT** universal float-casting constructor. Could work with separate raw config storage/adapters, but number-preserving storage avoids inventing a float conversion when the current consumer has not performed one. |
| Canonical number-preserving `Duration` | **LOCALLY PROVED:** candidate stores exactly the incoming int/float; factories use existing multiply/divide expressions; arithmetic retains Duration, ratios return float, signed/zero/huge finite history remain. `duration_numeric_preservation`, `duration_arithmetic`, `signed_raw_elapsed`. | **ADMIT / SELECT** for typed algorithm quantities. Keep raw mutable config ints and transport DTO scalars. Preserve each consumer's conversion/rounding order rather than forcing all uses through a new rounded getter. |
| TimeUnit enum alone / `(magnitude, TimeUnit)` value | **DOCUMENTED:** Enum gives named members, not a magnitude or conversion engine. [Enum](https://docs.python.org/3.11/library/enum.html) **DESIGN JUDGMENT:** a pair with defined conversions/operators is a legitimate unit-bearing value. | **REJECT** enum alone as duration. **CONDITIONAL** pair when source-unit retention matters. This application stores canonical seconds; normalize at factories instead of carrying arbitrary unit pairs throughout arithmetic. Keep unit labels at input/display boundaries. |
| Separate Seconds/Milliseconds/Minutes NewTypes or wrapper classes | **DOCUMENTED:** NewType is nominal to checkers but runtime values are the original underlying objects. [typing](https://docs.python.org/3.11/library/typing.html) **LOCALLY PROVED:** mixed nominal numeric arithmetic is accepted; branding does not convert or validate. Separate full wrappers can enforce operators but require cross-unit rules. | **CONDITIONAL** minimal boundary-only intervention; **REJECT as selected arithmetic model**. One Duration avoids preserving a family of unit identities after quantities have already been normalized. Aliases are documentation only, not distinction. |
| Qt elapsed/deadline timers | **DOCUMENTED:** timers measure elapsed/expiry using their clock and have integer duration/sentinel behavior; they are not arbitrary signed historical quantity containers. [Qt 6.5 QElapsedTimer](https://doc.qt.io/qt-6.5/qelapsedtimer.html), [QDeadlineTimer](https://doc.qt.io/qt-6.5/qdeadlinetimer.html) | **CONDITIONAL** GUI timing; **REJECT** shared/headless duration or raw history replacement. Qt dependency and timer semantics solve a different responsibility. |
| Pint Quantity | **DOCUMENTED:** unit conversion and dimensional operations; registry/unit serialization concerns; generic type parameter describes magnitude, not a demonstrated static metre/second distinction. [tutorial](https://pint.readthedocs.io/en/stable/getting/tutorial.html), [typing](https://pint.readthedocs.io/en/stable/advanced/typing.html), [serialization](https://pint.readthedocs.io/en/stable/advanced/serialization.html) | **CONDITIONAL, documentation-only**: a credible broader dimensional engine. **DESIGN JUDGMENT:** not selected for two narrow dimensions because this adds dependency/registry/adapters and a broader API contract. No claim of measured speed, memory or startup cost; Pint is absent and untested. |
| Named int/float seconds, standard numeric representations | **LOCALLY PROVED/source:** config and framework/wire callers require scalar kinds; existing `int`, `//`, `ceil`, round, clamp meanings differ. Decimal/Fraction provide numeric representation, not elapsed-unit identity. [numeric overview](https://docs.python.org/3.11/library/numeric.html) | **ADMIT** raw config, IO adapters and short local scalar formulas. **REJECT** as the only shared arithmetic contract when Duration communicates intent and preserves dimension through operations. |

**LOCALLY PROVED:** `timedelta_contract` verifies negative/zero behavior, arithmetic,
ratio, half-even microsecond rounding and overflow for 1e100/10**400 seconds.
`decoder_huge_finite` verifies current daily decoding accepts 1e100, negative and
zero seconds while rejecting NaN; this duration-history range is much wider than
renderable timestamp range. The selected Duration adds no global bound or finite
check: validation remains at existing decoders and config/consumer rules.

The deterministic wall operands `old = 2**30`, `now = old + 2**-22` yield
`2.384185791015625e-7` seconds. timedelta rounds that difference to zero. More
materially, `now = old + 300 + 2**-22` gives **300.0000002384186** seconds. The
current `TIME_JUMP_THRESHOLD_SECONDS = 300` plausibility condition rejects this;
timedelta rounds it to 300 and accepts it. `signed_raw_elapsed` proves selected
Duration retains both raw differences and the branch outcome. This is a bounded
arithmetic counterexample, not a live clock-resolution or suspend measurement.

The int-versus-float distinction also matters before rounding. For
`n = 2**60 + 59`, existing `n // 60` is **19215358410114117**, while
`int(n / 60)` is **19215358410114116**. The probe retains the former at floor
consumers and the original `ceil(n / 60)` at variation consumers; it does not
“improve” the latter into a different integer formula. A 401-digit raw integer
config duration survives loader/validation/formatting and candidate construction.
No promise is made that every later float API accepts every arbitrary integer;
existing overflow/conversion behavior must remain visible at its original seam.

```python
# Current: raw integer config and fractional elapsed paths
elapsed = now - last_observation
elif idle_ms / 1000.0 < elapsed:
    self._stats.add_active_time(state, elapsed)
cfg.automation.sit_duration = self.sit_dur.value() * 60

# Proposed: same raw subtraction, scale and integer operation order
elapsed = current_wall - previous_wall              # Duration
idle = Duration.from_milliseconds(idle_ms)           # value / 1000.0
if idle < elapsed:
    self._stats.add_active_time(state, elapsed)       # domain API
cfg.automation.sit_duration = self.sit_dur.value() * 60  # still int
picked_minutes = int(duration.seconds) // 60         # existing floor policy
variation_minutes = math.ceil(cfg.automation.sit_variation / 60)
qt_timeout_ms = int(duration.seconds * 1000)          # existing truncation
deadline = current_wall + Duration.from_minutes(minutes)
```

**DESIGN JUDGMENT / LOCALLY PROVED:** the candidate intentionally supports a narrow
arithmetic surface: Duration ± Duration → Duration; multiplication/division by
scalar → Duration; Duration / Duration → float; same-domain comparisons; abs.
It is not a replacement numeric ABC. Runtime incompatible operations use explicit
type dispatch/NotImplemented, producing TypeError. No automatic conversion of a
raw number is permitted in domain addition or ordering.

Zero semantics need deliberate treatment: dataclass defaults alone would make a
zero object truthy. The candidate implements `__bool__` using the raw payload,
so zero is false and negative is true, matching current numeric truthiness.
`Duration(0) != 0`, and ordering against raw0 raises. Use typed zero/thresholds,
e.g. `Duration(0) <= elapsed <= Duration(TIME_JUMP_THRESHOLD_SECONDS)` and
`max(Duration(0), target-active)`. `sum(values)` starts with raw 0 and fails;
`sum(values, Duration(0))` works. These explicit constants/adapters are a real
cost compared with nominal numbers, proved in `duration_arithmetic`, and accepted
because domain arithmetic now preserves meaning. Optional values and existing
wire zero sentinels remain separate contracts; a false Duration does not mean
missing data. Payload annotations are not a new runtime validator; dynamic wrong
field types still require the existing boundary checks.

### Operational clocks and civil time
<!-- family: clocks -->

| Alternative | Evidence | Disposition for I09/I10/I12 |
| --- | --- | --- |
| `datetime`, `date`, `time`, timedelta | **DOCUMENTED:** calendar types provide date/time/aware/naive semantics and bounded calendar/microsecond resolution; subtraction behavior depends on tzinfo/awareness. [datetime](https://docs.python.org/3.11/library/datetime.html#datetime-objects), [available types](https://docs.python.org/3.11/library/datetime.html#available-types) | **ADMIT** existing date totals and datetime rendering; **CONDITIONAL** parsed time endpoints internally. **REJECT** universal float-reading replacement: adds precision and timezone arithmetic decisions. Retain validated HH:MM and the current local minute/day evaluator. |
| `time.time`, `time.monotonic` raw floats | **DOCUMENTED:** epoch wall time versus undefined monotonic origin; only differences of monotonic readings are meaningful. [time APIs](https://docs.python.org/3.11/library/time.html#time.monotonic) | **ADMIT existing producers**, with wrappers formed after reading. Named raw numbers suffice inside an isolated adapter; **CONDITIONAL** across modules because identical float units do not prevent unlike-clock operations. |
| time_ns/monotonic_ns | **DOCUMENTED:** integer nanosecond interfaces avoid float representation loss; no promise of nanosecond clock resolution or clock-domain nominal type. BOOTTIME separately specifies suspend inclusion. [time_ns](https://docs.python.org/3.11/library/time.html#time.time_ns), [CLOCK_BOOTTIME](https://docs.python.org/3.11/library/time.html#time.CLOCK_BOOTTIME) | **CONDITIONAL** separately authorized precision/clock change; **REJECT** silently replacing existing float producers during typing. |
| Separate wall/monotonic NewTypes / Annotated float | **DOCUMENTED:** nominal checked inputs or consumed metadata, not restricted numeric arithmetic. [typing](https://docs.python.org/3.11/library/typing.html) | **CONDITIONAL** input-only protection, **REJECT selected operational model**: cross-clock arithmetic remains possible. A time unit enum does not encode provenance. |
| WallInstant/MonotonicInstant with selected Duration | **LOCALLY PROVED:** both unlike-clock subtraction directions fail static/runtime; same-clock subtraction preserves signed raw float difference, ±Duration retains clock. Addition of another instant, ordering unlike clocks and raw numeric duration addition fail runtime. | **ADMIT / SELECT** operational boundary values. Construction stores the raw reading, without datetime conversion, rounding or new range/finiteness policy. Scalar extraction bypasses protection and a caller can still mislabel a raw value. |
| Qt QElapsedTimer/QDeadlineTimer | **DOCUMENTED:** Qt 6.5 exposes timer clock queries and elapsed/deadline APIs, including coarse/precise/infinite and expired-remaining behavior. [elapsed](https://doc.qt.io/qt-6.5/qelapsedtimer.html), [deadline](https://doc.qt.io/qt-6.5/qdeadlinetimer.html) Current Python documentation's always-steady implementation is stated since6.6. [current binding](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QElapsedTimer.html) | **CONDITIONAL** GUI-local waits/receipt aging, **REJECT** core/headless and wall-snooze substitution. Do not use clamped remaining time where signed elapsed is needed, or assert6.6 guarantees at6.5. No timer migration selected. |
| Pint unit-aware time | **DOCUMENTED:** duration units can be checked by dimension; the tutorial does not supply this application's wall-versus-monotonic origin contract. [Pint tutorial](https://pint.readthedocs.io/en/stable/getting/tutorial.html) | **CONDITIONAL** duration engine, **REJECT** as sufficient clock-provenance representation. No local Pint result. |

```python
# Current: machine tick and GUI/tray progress interpolation
time_elapsed = now - self._last_check
is_time_jump = not (0 <= time_elapsed <= TIME_JUMP_THRESHOLD_SECONDS)
elapsed = time.monotonic() - self._progress_stamp
shown = max(0.0, self._remaining - elapsed)

# Proposed: preserve source clock and subtract raw float payloads first
time_elapsed = now - self._last_check  # WallInstant - WallInstant -> Duration
is_time_jump = not (Duration(0) <= time_elapsed <= Duration(TIME_JUMP_THRESHOLD_SECONDS))
elapsed = MonotonicInstant(time.monotonic()) - self._progress_stamp
shown = max(Duration(0), self._remaining - elapsed)
# Formatter/wire needs an explicit scalar if its interface remains primitive:
shown_seconds = shown.seconds
```

**LOCALLY PROVED/source:** machine/accounting wall differences retain backwards
and >300s reset/discard decisions; snooze and Bluetooth scan-cache aging remain
wall-derived. BLE grace, tick overrun, live-height throttle and GUI receipt aging
remain monotonic. `clock_domain_separation` and `signed_raw_elapsed` prove the
candidate operators, not platform suspend behavior. **DESIGN JUDGMENT:** use the
corresponding instant for a deadline; a redundant generic Deadline class adds no
needed operation. Keep `None` internally where present and0.0 absent/pending on
wire. Historical LogEntry/TransitionRow timestamps remain validated raw DTO floats
for datetime rendering, not obligatory operational objects that are immediately
unwrapped again. Local overnight/equal-start-end schedule behavior, DST and
timezone policy are unchanged. **UNRESOLVED:** no live timing, scheduler or
suspend measurements are asserted.

### Physical length, desk height and tolerance
<!-- family: length -->

| Alternative | Capability and evidence | Disposition for I01–I03 |
| --- | --- | --- |
| stdlib float/Decimal/Fraction | **DOCUMENTED:** numeric representations/operations, not physical units. The audited Python numeric chapter documents no physical-length quantity in that scope. [numeric](https://docs.python.org/3.11/library/numeric.html), [Decimal](https://docs.python.org/3.11/library/decimal.html), [Fraction](https://docs.python.org/3.11/library/fractions.html) | **ADMIT** current float magnitude; **REJECT** those alone as unit protection. **CONDITIONAL** different numeric precision contract; not selected. Changing current float arithmetic or the absolute-difference tolerance rule would change policy. This is not a claim to have exhaustively searched every stdlib module. |
| Existing HeightUnit / `(number, unit)` | **LOCALLY PROVED/source:** HeightUnit resolves display preference and authoritative .0254/100 conversions. Enum alone labels a unit; value+unit with defined operators can be a real quantity. | **ADMIT** HeightUnit and existing conversion policy; **CONDITIONAL** unit-bearing pair if source-unit retention matters. Normalize into Length for domain arithmetic; do not create a second preference mechanism. |
| Unified Length with unit factories/operators | **LOCALLY PROVED:** midpoint, distance, tolerance, ratio and cm/inch conversions preserve current expressions/order without `.metres` at every operand. Length±Length→Length, scalar scaling→Length, Length/Length→float. | **ADMIT / SELECT** typed domain length. Same dimension covers absolute heights and signed differences/tolerances; no affine/origin distinction is needed by the audited rules. Bounds stay in existing validators. |
| Nominal Metres / separate cm/in tags / aliases | **DOCUMENTED/LOCALLY PROVED:** checked-call identity but numeric arithmetic erases domain; constructors neither convert nor validate. [NewType](https://docs.python.org/3.11/library/typing.html) | **CONDITIONAL** low-intervention boundary alternative; **REJECT selected arithmetic model**. A single DisplayHeight tag still cannot identify cm versus inches, and aliases do not separate anything. |
| Pint physical quantities | **DOCUMENTED:** compatible conversion and dimensional errors, registry and serialization considerations; typing parameter is magnitude, not local proof of static units. [tutorial](https://pint.readthedocs.io/en/stable/getting/tutorial.html), [typing](https://pint.readthedocs.io/en/stable/advanced/typing.html), [serialization](https://pint.readthedocs.io/en/stable/advanced/serialization.html) | **CONDITIONAL documentation-only** broader engine, including compound dimensions/unit parsing. **DESIGN JUDGMENT:** current narrow Length/Duration do not justify selecting a registry dependency; if broad unit algebra were required, use a proven engine instead of extending these into one. No unmeasured cost assertion. |
| Qt QPointF/QSizeF/QRectF | **DOCUMENTED:** positions, extents and rectangles; float coordinates do not encode metre versus pixel. [Qt 6.5 point](https://doc.qt.io/qt-6.5/qpointf.html), [size](https://doc.qt.io/qt-6.5/qsizef.html), [rect](https://doc.qt.io/qt-6.5/qrectf.html) | **ADMIT GUI geometry; REJECT physical core length** and headless dependency. |
| Named metre primitives | **LOCALLY PROVED/source:** directly fit wire/config/idasen and local formulas. | **ADMIT** raw adapters; typed Length is selected inside connected domain operations. A wrapper is justified by retained arithmetic meaning, not an assertion that all primitive arithmetic is unclear. |

```python
# Current StateMachine and display conversion expressions
midpoint = (sitting_height + standing_height) / 2
at_preset = abs(height - preset) <= tolerance
fraction = (height - min_height) / (max_height - min_height)

# Proposed: the same expressions, now Length operands and typed results
midpoint = (sitting_height + standing_height) / 2  # Length
at_preset = abs(height - preset) <= tolerance    # bool, tolerance is Length
fraction = (height - min_height) / (max_height - min_height)  # float
height = Length.from_inches(displayed_number)    # existing value * .0254
height = Length.from_centimetres(displayed_number)  # existing value / 100
# The unit preference still chooses the existing conversion branch:
displayed_number = height.in_inches() if unit is HeightUnit.INCHES else height.in_centimetres()
wire_height = height.metres                      # only at primitive adapter
```

**DESIGN JUDGMENT:** use current HeightUnit/conversion implementation as the single
authority, either delegate from Length or adapt existing functions to it; do not
maintain two implementations. Temporary fixtures independently reproduce those
formulas and compare their outputs to the current helpers in `length_arithmetic`.
They are comparison evidence, not a proposal to duplicate formulas in production.
Stored config heights never round-trip through displayed precision. Preserve .02m
movement tolerance, separate RangeRail.MATCH .0075m, .01m preset slack and four
decimal save rounding. Zero unknown-height wire representation and optional read
failure remain adapters. A Length is neither proof of desk range nor of arrival;
command bool/read-back/interruption policy stays. Candidate zero truthiness uses
its magnitude; equality against raw0 is not supported as domain equality.

### Ratios, fractions, shares and blend amounts
<!-- family: ratios -->

| Alternative | Evidence | Disposition for I13 |
| --- | --- | --- |
| Fraction | **DOCUMENTED/LOCALLY PROVED:** exact rational arithmetic, supports negatives/>1; Fraction(float) records that float's rational value rather than intended decimal. [Fraction](https://docs.python.org/3.11/library/fractions.html) | **CONDITIONAL** deliberate rational contract; **REJECT** automatic bounded share or preservation of current float arithmetic. |
| Decimal | **DOCUMENTED/LOCALLY PROVED:** decimal context/rounding, signed/special values; Decimal(float) retains binary approximation. [Decimal](https://docs.python.org/3.11/library/decimal.html) | **CONDITIONAL** deliberate decimal contract; **REJECT** bounds validator/drop-in current ratio replacement. |
| Bounded 0–1 value | **DESIGN JUDGMENT:** requires an explicit interval/finiteness policy, not a dataclass annotation. | **CONDITIONAL only after existing clamp**, e.g. rail output, if that value crosses a useful typed boundary. **REJECT globally**: current finite signed history produces -1 or2 shares in the fresh case. No new chart clamp/validation authorized. |
| Generic Ratio / Pint dimensionless value | **DOCUMENTED:** dimensional cancellation is not a bounds proof. [Pint tutorial](https://pint.readthedocs.io/en/stable/getting/tutorial.html) | **CONDITIONAL** broader unit engine; selected narrow quantities return float ratios. No local Pint check. |
| Share/Progress/Blend NewTypes or unit enum | **DOCUMENTED:** tags separate checked arguments, not bounds/arithmetic. [typing](https://docs.python.org/3.11/library/typing.html) **DESIGN JUDGMENT:** a unit label adds nothing to a dimensionless local calculation. | **CONDITIONAL** repeated cross-module confusion; **REJECT** blanket local tagging or unit enums. |
| Named float plus existing clamp/QColor | **LOCALLY PROVED/source:** `_clamp01` is extracted and run unchanged; chart historical shares remain unbounded; QColor already holds actual colors. | **ADMIT / SELECT** role names and current clamp placement. Preserve locale.percent raw float input; DPR is not a bounded fraction. |

`ratio_numeric_alternatives` proves these counterexamples without a chart/widget
instance. Retaining float is a positive contract-preservation decision, not an
omitted exactness option. For I01 length→rail mapping, the selected length ratio
becomes a float before existing clamp and logical-pixel arithmetic.

### Qt geometry, pixels, font metrics and colors
<!-- family: qt-values -->

| Alternative | Evidence | Disposition for I14 |
| --- | --- | --- |
| Existing Qt point/size/rect/color values | **DOCUMENTED:** Qt 6.5 native APIs describe coordinate/extent/rectangle/color operations. [QPointF](https://doc.qt.io/qt-6.5/qpointf.html), [QSizeF](https://doc.qt.io/qt-6.5/qsizef.html), [QRectF](https://doc.qt.io/qt-6.5/qrectf.html), [QColor](https://doc.qt.io/qt-6.5/qcolor.html) **LOCALLY PROVED:** value-only geometry and RGB construction on Qt 6.11.2; no application object. | **ADMIT / SELECT GUI values**. C++ floor documentation and current Python runtime evidence are distinct; no actual6.5 binding test is claimed. |
| stdlib tuple/dataclass positions or RGB tuples | **DOCUMENTED:** named structure, no native Qt coordinate/color behavior. [dataclasses](https://docs.python.org/3.11/library/dataclasses.html) | **CONDITIONAL** Qt-free shared geometry; **REJECT** replacing established GUI values and adding adapters here. |
| PixelLength with coordinate-space enum / LogicalPoint and DevicePoint | **DESIGN JUDGMENT:** a value+space can require an explicit mapping, whereas an enum label alone does not scale. Physical Length still needs a DPR mapping for pixels. | **CONDITIONAL** recurrent shared space-conversion interface. Not selected for confined painting math. |
| Separate logical/device pixel NewTypes | **DOCUMENTED:** checked arguments only, arithmetic and runtime remain scalars. [typing](https://docs.python.org/3.11/library/typing.html) | **CONDITIONAL** useful conversion API; **REJECT** blanket wrappers for every painter operand. |
| Named numeric primitives/DPR | **DOCUMENTED:** Qt application geometry is device-independent, while image buffers contain device pixels mapped by DPR. [High DPI](https://doc.qt.io/qt-6/highdpi.html) **LOCALLY PROVED:** 22logical×1.5→33physical with existing round. | **ADMIT / SELECT alongside Qt types**. Preserve logical RTL mapping and float geometry until current integer boundary. Font points, weight600 and RGB channels are not one pixel dimension. |

The existing selectable_icon render path scales the buffer with
`round(box * dpr)`, sets DPR metadata and paints in logical coordinates. The proof
checks the scale arithmetic and native value APIs, not a QPixmap/platform plugin
or screenshot. **UNRESOLVED:** floor-specific Python binding behavior is supported
only by versioned Qt API documentation and current bindings, not a6.5 runtime.
No QElapsedTimer/QDeadlineTimer replacement is needed merely to use Qt values.

### Categories, literals, metadata and source-code meanings
<!-- family: categories -->

| Alternative | Actual guarantee | Disposition for I15/I21 |
| --- | --- | --- |
| Plain Enum / existing StrEnum | **DOCUMENTED:** named member families; StrEnum available in Python 3.11. [enum](https://docs.python.org/3.11/library/enum.html) **LOCALLY PROVED:** plain Enum member is not equal to raw1. | **ADMIT / SELECT** plain Enum for new portal internal vocabulary when needed; retain existing state/preference StrEnums and unknown-value records. Do not activate unused appearance preferences. |
| IntEnum / integer nominal tags | **DOCUMENTED/LOCALLY PROVED:** IntEnum behaves as int and integer arithmetic loses enum status. NewType preserves raw identity. [enum](https://docs.python.org/3.11/library/enum.html), [typing](https://docs.python.org/3.11/library/typing.html) | **CONDITIONAL** explicit integer interop; **REJECT** as a stronger runtime separation claim. Raw external codes still require decoding. |
| Literal | **DOCUMENTED:** checker restriction, no runtime validation. [Literal](https://docs.python.org/3.11/library/typing.html#typing.Literal) **LOCALLY PROVED:** unexpected literal is rejected statically, accepted by a Python function at runtime. | **CONDITIONAL** small internal choices; **REJECT** closing open historical strings or response-code failure policy. |
| Annotated unit/range metadata | **DOCUMENTED:** consuming tools determine meaning; otherwise underlying type. [Annotated](https://docs.python.org/3.11/library/typing.html) **LOCALLY PROVED:** inert annotation accepts out-of-range value. | **ADMIT** existing D-Bus signature consumer; **REJECT** assuming metadata validates units/range or swaps portal/Qt meanings. |
| Native Qt enums | **DOCUMENTED:** ColorScheme exists in6.5 source; Unknown0/Light1/Dark2; ContrastPreference introduced6.10. [Qt 6.5 source](https://raw.githubusercontent.com/qt/qtbase/v6.5.0/src/corelib/global/qnamespace.h), [ColorScheme](https://doc.qt.io/qt-6/qt.html#ColorScheme-enum), [ContrastPreference](https://doc.qt.io/qt-6/qt.html#ContrastPreference-enum) | **ADMIT** native enum at its own GUI API. **REJECT** numerical reinterpretation of portal code and post-floor contrast enum dependency without a supported fallback. |
| Named validated raw codes, constants/maps | **LOCALLY PROVED/source:** current portal decoder rejects bool/noninteger/unknown to None; Background treats0success/1cancel/otherfailure; journal maps priorities; subprocess has own return codes. | **ADMIT / SELECT external adapters**, explicit enum decoding only after current validation. A universal Code quantity/unit enum is inapplicable to independent vocabularies. |

**DOCUMENTED:** portal color-scheme codes are0 no-preference,1 dark,2 light.
[portal Settings](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Settings.html)
**LOCALLY PROVED:** the actual `_read_one` body is executed with fake message,
variant and connection collaborators; True,9,None become absence, while0/1/2
survive and contrast2 remains absent. The exact semantic Qt map is:

```python
portal_to_qt = {
    0: Qt.ColorScheme.Unknown,
    1: Qt.ColorScheme.Dark,    # Qt value 2
    2: Qt.ColorScheme.Light,   # Qt value 1
}
```

This is mapping evidence, not new appearance behavior. Current application
unknown-input→None policy is retained even where an external specification
suggests a no-preference fallback. **UNRESOLVED:** no live portal/backend or floor
binding call was exercised. Qt contrast6.10 remains explicitly beyond the6.5 floor.

### Resources, identities, descriptors and numeric counters
<!-- family: resources -->

| Alternative | Responsibility and evidence | Disposition for I16–I18 |
| --- | --- | --- |
| Existing dbus-fast low-level fd index/list and SleepInhibitor | **DOCUMENTED:** low-level body index differs from high-level actual fd; caller manages close. [type system](https://dbus-fast.readthedocs.io/en/latest/type-system/index.html), [low-level API](https://dbus-fast.readthedocs.io/en/latest/low-level-interface/index.html) **LOCALLY PROVED:** production extraction/release bodies run with fake closers. | **ADMIT / SELECT owner plus named primitives**. No hypothetical library-owned descriptor abstraction inferred. Current docs agree with existing source; no new dbus-fast floor API selected. |
| os.fdopen / file objects | **DOCUMENTED:** file object wraps an existing descriptor with stream/lifetime behavior. [fdopen](https://docs.python.org/3.11/library/os.html#os.fdopen) | **CONDITIONAL** actual file IO; **REJECT** unnecessary inhibitor stream/lifetime substitution. The resource is a held lock, not data being read. |
| contextlib.closing / ExitStack / owner context manager | **DOCUMENTED:** lexical cleanup and callbacks/transfer; integer itself has no close method. [contextlib](https://docs.python.org/3.11/library/contextlib.html) | **CONDITIONAL** acquisition rollback/owner helper where clearer; **ADMIT** existing longer-lived owner. An acquire-local with block would release too soon on return. |
| QDBusUnixFileDescriptor | **DOCUMENTED:** Qt 6.5 wrapper duplicates/manages its copy; supplied original still needs closure. [Qt fd wrapper](https://doc.qt.io/qt-6.5/qdbusunixfiledescriptor.html) | **CONDITIONAL** suitable Qt D-Bus code; **REJECT** daemon/headless dependency and harmless-scalar-replacement claim. Do not assume newer take/give APIs at the floor. No real descriptor probe. |
| NewType FdIndex/Fd/NotificationId or opaque owning handle | **DOCUMENTED:** nominal checked inputs do not supply lifetime. [typing](https://docs.python.org/3.11/library/typing.html) **DESIGN JUDGMENT:** an owning handle needs transfer/borrow/close rules separate from identity. | **CONDITIONAL** repeated typed role crossings; **REJECT** blanket tags, duplicate ownership, new UUIDs or a generic quantity for identity. |
| Named ints / existing named configuration and state | **LOCALLY PROVED/source:** fd index, actual fd, notification identity, PID/UID, generation, collection index, bounded limit and schema version have different uses. | **ADMIT / SELECT** confined roles. Preserve negative code/index sentinels, collection math and limits. A unit-bearing numeric algebra is inapplicable to notification identity or ownership. |

`fake_fd_ownership` compiles the current `_descriptor_from` and release method
bodies into a fake namespace: body index0 selects actual fd0, spare9 is closed;
release closes owned0 once, clears to None and a second release does nothing.
Invalid index closes all spares; absent reply is not fd0. The fake closer records
numbers only; no real descriptors or OS-close calls occur. This validates the
existing owner more directly than inventing a wrapper around its retained int.

### Records, member quantities and wire shape
<!-- family: records -->

| Alternative | Capability and limit | Disposition for I19–I21 |
| --- | --- | --- |
| NamedTuple / collections.namedtuple | **DOCUMENTED:** named fields plus tuple indexing/order/unpacking; keyword construction allowed, not required. [namedtuple](https://github.com/python/cpython/blob/v3.11.14/Doc/library/collections.rst), [NamedTuple](https://docs.python.org/3.11/library/typing.html) | **ADMIT / SELECT** existing daily/transition raw DTOs and new chart role record. Same-type positional swaps remain possible; prefer keywords at ambiguous producer. |
| TypedDict | **DOCUMENTED:** ordinary dict runtime, static shape without generated validation. [TypedDict](https://docs.python.org/3.11/library/typing.html#typing.TypedDict) | **ADMIT** object-shaped LogEntry; **REJECT** replacing array rows with dict shape silently. |
| dataclass, frozen or keyword-only | **DOCUMENTED:** generated record behavior; keyword-only fields force named construction, not correct semantic assignment. [dataclasses](https://docs.python.org/3.11/library/dataclasses.html) | **ADMIT** existing config/events/DurationParts and quantity/instant candidate records. **CONDITIONAL** chart dataclass if explicitly adapting all tuple consumers; not selected because tuple compatibility is useful. |
| Qt point/size/rect, generic QVariant containers | **DOCUMENTED:** native geometric roles. [QRectF](https://doc.qt.io/qt-6.5/qrectf.html) | **ADMIT** geometry; **REJECT** label/sit/stand/today record or Qt-free storage replacement. |
| tuple aliases / NewType tuple / bare tuples | **DOCUMENTED:** alias has structural identity, NewType no new field access. [typing](https://docs.python.org/3.11/library/typing.html) | **ADMIT** short heterogeneous local tuples where roles are clear; **REJECT** selected improvement for two adjacent same-unit chart values. A quantity or unit label cannot distinguish sitting from standing. |

**DOCUMENTED:** default JSON maps tuple/list to array and dict to object, not
arbitrary quantity/dataclass/instant objects; standard SQLite mappings likewise
do not automatically store such objects. [JSONEncoder](https://docs.python.org/3.11/library/json.html#json.JSONEncoder),
[SQLite types](https://docs.python.org/3.11/library/sqlite3.html#sqlite-and-python-types)
**LOCALLY PROVED:** `records_and_json` verifies existing DailyStatRow field/index/
unpack/JSON behavior, chart same-type swap possibility, keyword-only positional
rejection, nested asdict shape and explicit scalar encoding.

**DESIGN JUDGMENT:** retain **raw transport DTO members**: DailyStatRow.seconds and
TransitionRow.timestamp remain float, LogEntry retains scalar JSON params, and
wire aliases retain transport metadata. Domain `Stats.add_active_time(Duration)`
unwraps before SQLite; daily queries return the existing scalar DTO. Domain chart
composition converts each raw scalar once into Duration if the chart adopts the
typed domain API. This uses the existing raw record and the one differently
shaped chart record, not a duplicate hierarchy of identical domain/wire rows.
Historical log/timestamp renderers can consume raw decoded timestamps directly.

```python
# Current: GUI-local tuple obscures adjacent same-type roles
rows.append((label, sit, stand, is_today))

# Proposed chart boundary: raw DTO scalars -> one named domain record
class DailyChartRow(NamedTuple):
    label: str
    sit: Duration
    stand: Duration
    is_today: bool

row = DailyChartRow(label=label, sit=Duration(sit),
                    stand=Duration(stand), is_today=is_today)
# Indexing/unpacking still work, but quantity MEMBERS need scalar encoding:
json_payload = [row.label, row.sit.seconds, row.stand.seconds, row.is_today]
# json.dumps(row) is NOT automatically valid with these object members.
```

Changing the outer record type and changing its members are separate compatibility
decisions. `asdict` is not the old tuple array or scalar JSON contract. No boolean
or field annotation alone validates incoming data or a sitting/standing role.

## Repository-wide inventory and currentness

**LOCALLY PROVED/source:** source/tests match the previous inventory byte-for-byte;
all original 63 production Python files and I01–I21 anchors remain applicable.
No boundary addition/removal/meaning change was found. The earlier 2,081-site AST
search is historical inventory provenance, not newly repeated alternatives
research. Current grouped producer → conversion → arithmetic → storage → consumer
chains are retained below, with selected representations supplied by the executive
mapping and eight comparisons above.

| ID / domain, unit and clock | Producer and conversion / validation | Arithmetic and in-memory fields | Storage / wire and final consumers | Current source anchors |
| --- | --- | --- | --- | --- |
| I01 Desk height; metres, no clock | BLE `_decode_height`: uint16 tenths-of-mm above 0.62 m → `raw / 10_000 + MIN_HEIGHT`; library height read; MockDesk; preset/migration inputs. Port returns optional float; errors preserve `None`. | Machine `last_height`, event `height`/`final_height`; daemon gesture start/return heights; classify midpoint; compare read-back against target ± tolerance. | Config metres; no height column in current stats schema. D-Bus Height/MoveToHeight/Save/Setup/CaptureCurrent and HeightChanged use double. GUI receives float, Overview/rails/presets render or move; CLI snapshot formats metre Height and sends named gesture/preset commands (no raw-height CLI command). | [DeskPort](../src/idasen_companion/desk/port.py#L12); [BLE decode and adapter](../src/idasen_companion/desk/ble.py#L68); `StateMachine._classify`, `_drive_transition`; `Daemon._manual_move_locked`; `Desk1`; `DaemonClient._on_height`; `cli._read_status` |
| I02 Display numbers; cm/in versus metres | `HeightUnit` resolves independently of language; `to_display_height` divides by 0.0254 or multiplies by 100; inverse converts user input. GUI spin values are displayed numbers. | Overview `_height`/`_target` retain metres across display preference changes; spin decimals 1 cm/2 in, steps 0.5 cm/0.25 in. Config height is not round-tripped through a rounded display value. | Stored and sent heights remain metres; formatter, wizard and preset page are consumers of display floats/strings. CLI uses same formatter. | [display conversions](../src/idasen_companion/core/display_prefs.py#L141); `Formatter.to_display_height`, `from_display_height`; `OverviewPage._shape_height_spin`, `_on_spin_changed`; `PresetsPage`; `SetupWizard` |
| I03 Length tolerances/ranges; metres | Config movement_tolerance default .02, validation `0 < tolerance < .5`; physical .62–1.27 with .01 preset slack; saver rounds preset metres to four decimals. | `abs(height - preset) <= tolerance`; midpoint separates state, tolerance determines at-preset; GUI RangeRail.MATCH is a separate .0075 m display-match tolerance; rail coordinate formula converts metres to a dimensionless fraction and logical px. | TOML tolerance and presets are floats; machine interruption/yield/adopt rules and GUI rail/tick position consume them. Position enums already express classification result. | [config validation](../src/idasen_companion/core/config.py#L314); `StateMachine._cycle_state_for_height`, `_classify`; `HeightRail._x`, `_meters`; `RangeRail._y` in [widgets](../src/idasen_companion/gui/widgets.py#L735) |
| I04 Configuration durations; integer seconds | `parse_duration`: integer h/m/s groups; raw non-bool ints accepted by `_apply_section`; mutable defaults determine runtime types. Positive check_interval and sit/stand durations; nonnegative variations/thresholds/sync; no universal positivity constraint. | `target_duration` whole seconds, random variation `ceil(variation / 60)` then `randint * 60`; GUI minutes shown via `//60`, applied via `*60`; duration parts named hours/minutes/seconds. | TOML compact strings, raw integer seconds accepted on read. Integer config fields feed core gates, BLE linger, daemon tick and notification lead time. GUI presets of duration choices stay integer seconds; sync 0 disables normal sync, held poll still operates. | [config models](../src/idasen_companion/core/config.py#L130), `_DURATION_FIELDS`, `_apply_section`, `_validate`, `save_config`; [durations](../src/idasen_companion/core/durations.py#L34); `StateMachine._next_target_duration`; `AutomationPage._load`, `_apply` |
| I05 Elapsed/active/remaining time; fractional seconds, wall-derived | Daemon `_tick` supplies time.time to `ActiveTimeAccounting.account` and machine tick; signed differences from prior observations. Plausibility `0 <= elapsed <= TIME_JUMP_THRESHOLD_SECONDS` guards current credit. | Machine active_time float, integer target; pending credit dict keyed original day/state; silence confirmed/cleared, `max(0,target-active)` for remaining. Pending accounting belongs to Stats observation clock, independent of frozen automation. | SQLite daily.seconds REAL, JSON row seconds, D-Bus ActiveTime/TargetDuration/TimeRemaining and ProgressChanged dd, Qt float pair. GUI/tray/CLI duration rendering floors/clamps per renderer; historical finite negative/zero daily values accepted. | [accounting](../src/idasen_companion/daemon/accounting.py#L11); `StateMachine.tick`, `time_remaining`; [Stats.add_active_time](../src/idasen_companion/daemon/stats.py#L127); `decode_daily_rows`; `StatisticsPage._refresh`; `TrayIcon._shown_elapsed`; `cli._status_text` |
| I06 Idle observations; integer milliseconds, provider-relative elapsed | Mutter reply int; ScreenSaver provider intentionally treats KDE reply as milliseconds despite spec mismatch noted in repository; X11 ctypes idle ulong → int. IdleMonitor failure returns 0 meaning assume active. | Machine `_last_idle_ms`, event idle_ms; comparisons to seconds thresholds `*1000`; accounting `idle_ms / 1000.0 < elapsed` preserves fractions. Absence start derived by subtracting idle seconds from wall now. | No idle DB column; diagnostic/log params convert to seconds; daemon/core presence gates consume ms. KDE/X11 behavior is source evidence, not hardware reverified here. | [idle providers](../src/idasen_companion/daemon/idle.py#L30); `IdleMonitor.get_idle_ms`; `StateMachine._update_presence`; `ActiveTimeAccounting.account`; `Daemon._handle_event` |
| I07 Snooze; integer minutes to seconds to Unix deadline | GUI fixed `_SNOOZE_MINUTES`, tray SNOOZE_CHOICES; D-Bus Snooze int32; daemon clamps `max(1,int(minutes))`. | `snooze_until = now + minutes *60`; optional float internally; state/status compares to wall now. | D-Bus SnoozeUntil double with 0.0 absent sentinel; Qt cached float also briefly 0 while async read pending. GUI/tray/CLI format local datetime from Unix seconds; no deadline persistence. | `StateMachine.snooze`; `Daemon.snooze`; [Automation1.Snooze](../src/idasen_companion/daemon/service.py); `DaemonClient._note_status`, `_set_snooze_until`; `OverviewPage._render_status`; `TrayIcon`; `cli._status_text` |
| I08 External microseconds; elapsed allowance versus Unix timestamp | logind InhibitDelayMaxUSec int >0 → /1_000_000 float; fallback 5s. Journal __REALTIME_TIMESTAMP → int /1_000_000 Unix seconds. | Inhibitor `_max_delay`, budget clamp min(10,max(1,delay-1)); journal timestamp decoded/rendered. Same input unit does not imply same kind. | D-Bus external scalar/variant only at adapter; budget enters daemon pre-sleep timeout; journal read produces LogEntry ts consumed GUI/CLI. | [SleepInhibitor._learn_max_delay](../src/idasen_companion/daemon/inhibit.py); `SleepInhibitor.budget`; `Daemon._release_desk_before_sleep`; [journal._entry_from_record](../src/idasen_companion/core/journal.py#L209) |
| I09 Unix instants; epoch seconds, wall clock | time.time in daemon, Stats transitions, RingLog; journal decode; JSON decode_timestamp checks finite and locally renderable, accepts negative/zero. | Machine `_last_check`, `_last_sync`, `_idle_since`, snooze_until; accounting `_last_observation`; Bluetooth scan-cache stamp uses wall time (not monotonic). Signed differences; datetime.fromtimestamp for schedule/day/time. | SQLite transitions.ts REAL, LogEntry ts, JSON arrays/objects, D-Bus log double/snooze double. GUI/tray/CLI historical local-time rendering. No global >0 timestamp invariant. | `Daemon._tick`, `_run_until_stopped`; `StateMachine.tick`, `status`; `ActiveTimeAccounting`; [Stats.record_transition](../src/idasen_companion/daemon/stats.py#L141); `RingLog`; `BluetoothSupport.discover`; `decode_timestamp`; `cli._log_text` |
| I10 Monotonic readings and deadlines; seconds, process/runtime clock | time.monotonic in BLE wakeup grace, daemon tick overrun/live-height throttle, GUI/tray progress stamp; asyncio owns relative wait deadlines. | `_awake_since`, `_last_height_emit`, `_progress_stamp`; same-clock differences → elapsed; remaining duration aged against local progress receipt, not daemon wall timestamp. | In-memory only; Qt ticker requests ms, notifications/progress carry durations, never a monotonic epoch. Final consumer BLE wake decision, emitted height throttling, GUI countdown/elapsed and diagnostics. | `BleDesk._controller_awake`, `_connect_with_retries`; `Daemon._on_live_height`, `_run_until_stopped`; [OverviewPage._on_progress](../src/idasen_companion/gui/pages/overview.py#L534); `TrayIcon._since_progress` |
| I11 Timeouts, retries, refresh delays; integer/fractional seconds or Qt ms | BLE retry tuple 1/2/4s, wakeup_grace 2s, read/connect 30s, disconnect 12s; dbus_util DEFAULT_TIMEOUT; Bluetooth scan timeout max0/min30; GUI 45_000/90_000/30_000 ms; notification timeout_ms default15000; portal 3000/30000 ms. | Async waits/sleeps use seconds; wizard `int(seconds*1000)` truncates to Qt milliseconds. Discover 0 means cached/paired only; local scan cache valid for wall 60s. Tickers 1000ms; singleShot(0) queues work rather than representing absence. | No schema. Primitive timeout arguments to asyncio/subprocess/Qt/Notify. Daemon IO, wizard, service_ctl, journal read, portal response loops, tray animation, About copy reset and activity-log deferred repaint consume local constants. | `BleDesk`; `dbus_util.call`; `BluetoothSupport.discover`; `DaemonClient.discover`, `setup`, `capture_preset`; `Notifier.send`; `SetupWizard._wait_for_daemon`; `service_ctl._run`; `journal.read_recent`; portal `_READ_TIMEOUT_MS`, `_RESPONSE_DEADLINE_MS`; `TrayIcon` |
| I12 Local schedule; HH:MM, minute-of-day and weekday index, civil clock | Config validates hour0–23/minute0–59 and valid day names; Qt QTime editor string; caller datetime.fromtimestamp(wall now). | `_minutes` → hour*60+minute; weekday0–6, yesterday modulo7; overnight window attributed to start day, equal bounds full24h. | TOML strings/day list; no duration/instant serialization. Only core schedule decision plus GUI schedule summary; display clock preference does not change window. | [schedule](../src/idasen_companion/core/schedule.py#L18); `config._parse_hhmm`; `AutomationPage._apply`; `StateMachine._frozen`, `status`; GUI schedule summary |
| I13 Fractions/ratios; dimensionless, varying range policies | Height min/max ratios, standing/overall, color mixing amount, normalized style mark coordinates, font scale factors. | `_clamp01` only for rail fractions; chart shares derive from historical signed seconds and are not universally clamped; `_mix` linearly blends RGB. DPR is positive scaling input rather than bounded fraction. | In-memory paint calculations / localized percentage strings; no external fraction contract. Rail interaction/paint, chart, Theme, style and locale percent formatter consume floats. | `HeightRail._x`, `_meters`; [widgets._clamp01](../src/idasen_companion/gui/widgets.py#L730); `DailyBarsChart.paintEvent`; `StatisticsPage._refresh`; `theme._mix`; `style._draw_mark`; `LocaleProfile.percent` |
| I14 Geometry/style primitives; logical px, physical px, points, RGB channels | Qt widget rectangles, mouse position, font metrics; design token ints; app DPR; font pointSizeF. | Physical pixmap size round(box*dpr), then setDevicePixelRatio; painter coordinates stay logical; RTL mirrors rail/chart. QColor RGB0–255, style normalized marks, pixel inset half-border; font weights600 and font points differ from px. | QSize/QRect/QPointF/QColor and CSS strings; GUI-only widgets/theme/style/main_window/presets/About/activity-log scrollbar consumers. Qt geometry already supplies records. | `selectable_icon.render` in [widgets](../src/idasen_companion/gui/widgets.py#L126); `HeightRail`; `DailyBarsChart._visual_rect`; `theme.control_height`, `extra_icon_gap`; `style.pixelMetric`, `_draw_mark`; `ActivityLogPage._on_scroll_range_settled` |
| I15 Numeric category codes; finite known families and open external codes | Portal color-scheme0/1/2, contrast0/1 validated as non-bool int; Background response0 success/1 cancel/other failure; journal priority map; subprocess exit code incl local -1 failures. | Category comparisons/maps, no quantity arithmetic; AppearancePreferences stores optional int, result dropped currently. Qt StateFlag/PixelMetric/IconMode already enums, state_values wraps unknown textual vocabulary. | External D-Bus uint/variant, journal numeric string, subprocess code; adapters → diagnostic/decision. Preserve unknown and absent distinctions; no new palette behavior. | [appearance_portal._read_one](../src/idasen_companion/gui/appearance_portal.py); `background_portal._judge`; `journal._PRIORITY_TO_LEVEL`; `service_ctl._run`; `command.main`, `cli.main`; `core/state_values.py` |
| I16 IDs/handles; opaque integers, optional or sentinel | os.getuid/getpid/proc directory; logind D-Bus fd index plus out-of-band unix_fds; notification returned ID; Qt metatype id/tray instance number; X11 window/root/display pointer, journal stream device/inode identity. | Descriptor index → actual fd selection; spare fds close, owner clears before close. Notifier compares `_last_id`; uid/PID identity compares only. Do not treat fd0 as absent; inhibitor uses None. | OS fds / D-Bus h index or u IDs; in-memory owner fields; os.close, logind GetUser, notification action routing, ctypes and Qt SNI packing consume primitive IDs. | [inhibit._descriptor_from](../src/idasen_companion/daemon/inhibit.py#L63); `SleepInhibitor.release`; `SessionActiveMonitor`; `BluetoothSupport._other_companion_daemons`; `Notifier`; `sni.pixmap_element_type`, `find_tray_connection`; `X11IdleProvider`; `journal.stdout_is_journal` |
| I17 Counts/limits/indices; integer, no physical unit | CLI --limit positive parser; Stats recent_transitions clamp1–1000; journal limit2000; RingLog maxlen500; 14-day chart offsets; retry attempts, mock get_height_calls/move generation, Qt selection indices. | Index/slice/range/len, generation equality; no cross-unit conversion. Selection index -1 and return code -1 are contextual sentinels, not global invalid-int policy. | SQLite LIMIT bound param, JSON selected rows, deque maxlen; chart/navigation/CLI consumers. Keep primitives: collection APIs express purpose and reject a wrapper poorly. | `cli._positive`, `_dispatch`; [Stats.recent_transitions](../src/idasen_companion/daemon/stats.py#L171); `journal.read_recent`; `RingLog.__init__`; `SegmentedControl.setCurrentIndex`; `BleDesk._stop_generation`; `MockDesk`; `StatisticsPage._refresh` |
| I18 Numeric metadata/formatting; integer counts, version, binary raw scalar | SQLite user_version1; app version string; decimal places/min_digits/plural counts; raw BLE uint16, unused second speed word; byte lengths/color channels. | Schema version comparison; numeric formatting/decomposition; unpack scaling only raw position. No speed quantity is exposed or consumed, so no Speed type justified. | DB PRAGMA, strings/markup, ctypes/binary boundary; Stats schema gate, locale formatters, translation plural APIs, desk decoder. Preserve primitives: named constant/local context already sufficient. | `stats.SCHEMA_VERSION`, `_NewerSchema`; `display_prefs.height_decimals`; `DurationParts`; `LocaleProfile.number`, `integer`, `plural_category`; `core/i18n.py`; `BleDesk._decode_height` |
| I19 Existing records; neighboring numeric roles | DailyStatRow/TransitionRow decode external rows; LogEntry dict; DurationParts decomposition; CLI StatusSnapshot properties; named machine Event dataclasses. | Named fields expose role, but seconds/timestamps remain float currently; decoders preserve unknown states and finite signed historical values. | NamedTuple daily/transition rows serialize unchanged as JSON arrays; LogEntry object shape unchanged; GUI/CLI use field names. Do not replace with dict/dataclass without array adapter. | [decoded records](../src/idasen_companion/core/decoded_data.py); `Stats.daily_totals`, `recent_transitions`; `Stats1`; `DaemonClient.get_daily_stats`, `get_transitions`; `cli.StatusSnapshot`; `core.machine.Event`; `DurationParts` |
| I20 Remaining chart row; label, sit seconds, stand seconds, today flag | StatisticsPage._refresh builds `(label,sit,stand,is_today)` from named daily rows; default zero for missing day/state. | DailyBarsChart `_rows` tuple list, unpack/index, max(sit+stand), segment widths and percentages; two floats can be swapped unnoticed. | GUI-local only, no DB/wire change. NamedTuple recommended for fields, preserving current indexing/unpacking; raw float or Seconds fields do not distinguish sit from stand. | [StatisticsPage._refresh](../src/idasen_companion/gui/pages/statistics.py#L115); [DailyBarsChart](../src/idasen_companion/gui/widgets.py#L973), `set_rows`, `_tooltip_for`, `paintEvent` |
| I21 Wire scalar aliases/payloads; signatures versus meanings | `DBusDouble`, `DBusInt32`, `DBusUInt32`; ProgressPayload dd, WarningPayload su, LogPayload dsssss; external JSON untyped numbers. | Signature validates transport kind, not unit. Progress names active_time/target_duration; external decoding float/int coercions do not prove domain validity. | Preserve D-Bus annotations/signatures, basic Qt signals and JSON shapes. Core/GUI/CLI domain values enter/exit through explicit adapters; do not expect Qt Signal(float,float) to preserve NewType or slot compatibility checking. | [service aliases](../src/idasen_companion/daemon/service.py#L38); `Automation1.ProgressChanged`; `DaemonClient._on_progress`, `_on_height`, `get_property`; `cli.Client`, `_read_status` |

Primitive candidates I04, I08, I11–I18 are positive design decisions, not an
unexamined remainder. Other tuples reviewed include preset marks `(label,metres)`,
scan cache `(wall stamp,device list)`, action `(label,callback)`, setup
`(ok,height-or-error)` and systemctl `(code,out,err)`: their names/unpacking and
heterogeneous members sufficiently explain their local roles. The chart's two
adjacent same-unit floats are a stronger case for a named record. Setup's union
could benefit from a result record in a broader API redesign, but creates no new
numeric quantity here. No RSSI quantity is consumed by the current discovery
path; BlueZ filtering produces names/MACs rather than signal-strength arithmetic.



## Compatibility and implementation consequences

| Contract / risk | Required preservation and selected adapter |
| --- | --- |
| Mutable config / integer kinds | Leave existing dataclass fields/keys/default runtime types and `_apply_section` inference intact. Raw arbitrary ints, duration grammar and existing bool/per-field checks remain. Construct Duration for typed operations without float-casting config. Preserve current integer floor, fractional division, ceil, truncation and save formatting exactly. |
| Accepted history / values | Daily finite negative/zero/huge values remain; timestamp renderability remains a separate decoder constraint. Quantity constructors impose no new global positivity/finiteness/physical-range limit. Existing clamp/threshold/round policies stay with their consumer. No duration quantization or global normalization of signed data. |
| Zero versus None / object semantics | Preserve sync0 off, discover0 cache-only, idle0 active/failure-open, target0 unseeded, height0 unknown, snooze0 absent/pending, timer0 queued work, fd0 valid and None absent. Candidate quantity bool uses payload, but raw0 equality/order and sum default require explicit typed constants/start. Keep optional checks explicit before unwrap. |
| Domain arithmetic / maintenance | Shared operators retain result meaning and reject unlike dimensions/clocks, but introduce constructor/operator/adaptation code and typed constants. Number-preserving fields mean consumers must handle int and float deliberately. No broad units registry, implicit conversion from raw operand, automatic rounding getter or claimed allocation/performance advantage. |
| SQLite / JSON | Preserve daily.seconds/transitions.ts REAL, interrupted INTEGER, schema1, row order/arity/open text, fail-soft behavior. Explicit scalar values go into binds and JSON; existing raw DTOs remain. No migration, output reshaping or historical rewrite. A quantity-bearing NamedTuple still needs scalar member adapters. |
| D-Bus / Qt | Keep current DBusDouble/int signatures and dd/su/dsssss payloads; JSON strings remain JSON strings. Unwrap domain objects before emission; decode primitive input into domain values inside typed entry points. Qt Signal(float,float), QVariant, Any and generic callbacks cannot carry static unit guarantees: use typed adapters rather than blanket casts. No new object through a decorator or Qt signal without an explicit boundary redesign. |
| Desk / external units | Preserve metres, BLE uint16 offset/10000+.62, optional reads, command bool versus arrival, tolerances/recovery. Keep KDE-specific ms interpretation/failure-open behavior and logind µs positive/fallback/headroom/clamps. Inhibit filter currently accepts bool as int; do not globally tighten it under typing. Journal µs → Unix float stays separate from µs duration. No external unit/hardware reprobe. |
| Clock/civil behavior | Keep wall vs monotonic producers, signed raw subtraction,300s plausibility/reset/discard, wall snooze/cache, monotonic receipt aging and explicit sleep lifecycle. No switch to datetime subtraction, ns producers or BOOTTIME; no claim every monotonic clock includes suspend. Local overnight/equal-endpoint schedule, DST, day attribution and display preference independence stay. |
| Qt floor / categories / dependencies | Keep Qt in GUI. Qt 6.5 manuals/source ground basic values/ColorScheme; current6.11.2 probes are not floor binding proof. Do not use ContrastPreference6.10 or always-steady6.6 guarantees at floor. Portal unknown/bool→None policy retained, dark/light mapped by meaning. Pint remains absent/documentation-only; no dependency installed or selected. |
| Resources / IDs | Keep owner transfer/close timing and spare cleanup, None checks, notification matching, current generation/index/limit/version semantics. No actual-fd/file-wrapper/Qt-wrapper swap or second owner. |

**DESIGN JUDGMENT:** an authorized implementation would connect producers, typed
domain signatures/operations and explicit scalar adapters together, then update
affected checks for typed constants, arithmetic, truthiness, DTO members and
framework boundaries. Begin by spelling out the shared Duration/Length/instant
contracts and boundary encoders; adapt connected producer/domain/consumer paths,
then preserve config/storage/wire shapes and distinct regression behavior. This
is a generic implementation consequence, not a height-first/timing-later rollout,
new assessment todo or permission to edit production code.

## Focused static and runtime evidence

The new temporary runner accepts `--repo-root`, `--report`, `--receipt`, uses the
already-cached mypy 2.3.0 and existing virtualenv, never installs a package and
keeps bytecode/checker caches in/tmp or disables them. It records a fresh run ID,
argv/versions/exit codes, complete expected/actual/unexpected diagnostics, all 12
runtime family booleans, every runtime process, source/fixture/report hashes and
one computed passed flag. Local ledger: quick `261020-fkh-EVIDENCE.md`.

| Evidence | Final scope and exact outcome |
| --- | --- |
| F01 preservation/currentness | 454 protected paths (all src/tests plus AGENTS.md, TODO.md, .planning/config.json); every path and digest checked, no digest-key collapse. Parent pre-snapshot453 paths also match; source/tests unchanged since prior inventory. |
| F02 static positive | Cached mypy 2.3.0, positive.py plus narrow quantities/clocks/static-support inputs, exit0. Unified operations, same-clock arithmetic, typed records accepted. Nominal mixed arithmetic and inert Annotated also intentionally accepted to expose limits. |
| F03 exact intended negative | Exit1, exactly 11 errors and six related overload notes, **17 complete normalized diagnostics**, none unexpected. Wrong dimension/raw height, mixed-clock operations both directions, instant-as-duration, invalid Literal and wrong record member rejected. Notes are matched, not silently ignored. |
| F04 runtime | One runtime process exit0, exactly12 required family assertions literally true: timedelta_contract; decoder_huge_finite; duration_numeric_preservation; duration_arithmetic; length_arithmetic; clock_domain_separation; signed_raw_elapsed; ratio_numeric_alternatives; enum_and_portal_mapping; qt_value_geometry; fake_fd_ownership; records_and_json. |
| F05 final gates | Both exact plan gates execute fresh examples; final receipt/report hash, source/probe hashes, I01–I21/eight-family coverage and complete preservation manifests checked. |

```sh
scratch=$(cat .planning/quick/261020-fkh-reassess-all-semantic-type-alternatives/261020-fkh-PROBE-DIR.txt)
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python "$scratch/run_probes.py" \
  --repo-root . --report docs/SEMANTIC-TYPES-ASSESSMENT.md \
  --receipt "$scratch/final-receipt.json"
```

**UNRESOLVED / evidence limits:** no migrated application, complete production
type check/full suite, bus/Qt signal interoperability, hardware, true descriptors,
live scheduling/suspend or performance measurement. Dynamic payload bypasses,
constructor clock provenance, nonfinite arithmetic/zero-division and all numeric
protocols are not universally guarded by these narrow candidates. Some related
operators are exercised only at runtime or only statically; claims above state
the particular tested operation. Pint has documentation evidence only. Floor
documentation and current local Qt behavior are different evidence, not proof
that every proposed API/binding works on6.5. The report makes no such guarantee.

## Evidence retention audit

Retain this revised report as the tracked deliverable and this new quick's local
evidence, protected manifests, pointer and SUMMARY. Scratch fixtures, runner,
candidate values, gates and atomic receipts stay in
`/tmp/idasen-semantic-reassessment-r_g4_hby/semantic-types-final.VBYasg`.
No permanent proof harness is introduced. The12 runtime families and11 intended
static error sites cover material choices, not a Cartesian research matrix.

Prior quick 261020-e17 proof receipts and research R1 observations are historical;
the current source inventory is reused only after currentness checking. Research
official-document results are attributed as DOCUMENTED; the new runner is the
evidence for LOCALLY PROVED candidate claims. Research's10,000-read wall-clock
observation was not repeated or used as fresh evidence; deterministic operands
now demonstrate the exact compatibility consequence.

Final retention counts: **0 new permanent tests, 0 expanded permanent tests,
0 removed permanent tests, 0 retained repository probes**. The full suite was not
run for this documentation-only change. All454 protected paths/hashes match;
source, tests, instructions, TODO/capture and configuration bytes are preserved.
No application/daemon/test-instance or Qt application object was launched,
inspected, interrupted or restarted; no bus/hardware/real fd, install, CI, remote
Git or release action occurred. Pure Qt values and AST-extracted functions with
fake collaborators are explicitly bounded local evidence. Parent owns Git and
selected capture closure after independent verification.
