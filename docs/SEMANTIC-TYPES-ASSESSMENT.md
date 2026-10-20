# Semantic types across numeric boundaries

Assessment of the current application, 2026-10-20. This document decides the
representation of numeric contracts together across core, daemon, desk, GUI and
CLI. It records an internal typing design; this assessment changes no application
behavior, schema, protocol, clock policy or source code.
Readability, explicit intent and maintenance are sufficient reasons for a type;
a demonstrated defect is not a prerequisite.

## Executive recommendation

Use a small shared vocabulary for quantities at typed domain interfaces, two
explicit clock value objects for instants, existing enums for closed vocabulary,
and named records for neighboring values with different roles. Keep ordinary
numbers inside arithmetic and framework adapters when names and immediate
context make their meaning clear. This is one design across all domains, not a
height-first rollout or a request for another assessment.

| Boundary family / inventory IDs | Recommended representation and placement | Actual guarantee | Deliberately unenforced / reason |
| --- | --- | --- | --- |
| Desk/config/display heights and tolerances, I01–I03 | `Metres = NewType("Metres", float)` in a Qt-free shared core module; type DeskPort, domain fields, event heights, formatter metre inputs and conversion outputs. Tolerance is also metres. | Checked callers cannot pass `Seconds` or a raw displayed number to a metre parameter. | No physical range, finiteness, origin/height-versus-distance distinction or dimensional arithmetic. Keep midpoint/difference arithmetic numeric; rebrand only deliberate results. Avoid a height object whose `.metres` obscures every expression. E03–E05. |
| Fractional elapsed/remaining/active seconds, I05 | `Seconds = NewType("Seconds", float)` at accounting, machine, statistics and formatter interfaces; named record fields carry it. | Rejects height, minutes, milliseconds and instant arguments at checked calls. | No positivity invariant: clock differences and historical statistics may be negative; no conversion or runtime validation. Plain local sums remain clearest. E03–E05. |
| Config integer seconds and duration parts, I04 | Retain `int` in mutable config records, parser, saver and whole-minute randomization; name adapter variables `*_seconds`, convert deliberately to `Seconds` entering fractional domain operations. | Existing parser/validation preserves integer grammar, per-field ranges and zero meanings. | A new nominal integer type on every config field would add coercion/getter work without separating neighboring same-unit fields. Do not make config seconds float or alter TOML keys. I04/E05. |
| Idle readings and snooze minutes, I06–I07 | `Milliseconds = NewType("Milliseconds", int)` at idle-provider → machine/accounting seam; `Minutes = NewType("Minutes", int)` at snooze commands; named conversion functions to `Seconds`. | Checked calls distinguish these units, with fractional division preserved. | No range validation from branding. Keep local Qt millisecond literals/constants primitive with `_MS` names; unwrap to `int` at Qt/D-Bus calls. E03–E05. |
| External microseconds and private timeout literals, I08, I11 | Primitive `int microseconds`, converted once; local `float timeout_seconds`, integer Qt `timeout_ms`. Brand only the seconds result when it leaves its adapter. | Named conversion makes scale and target explicit; existing positive/fallback/clamp rules remain. | No `Microseconds` ecosystem for two isolated adapters, and no new type for each timeout. Both share seconds with other durations. I08/E05. |
| Unix instants and monotonic instants/deadlines, I09–I10 | Small frozen `UnixInstant` / `MonotonicInstant` records with `.seconds`, `elapsed_since(same clock) -> Seconds`, `after(Seconds) -> same clock`; explicit comparison of same-clock scalars within algorithms. | Static separation; runtime class checks in **elapsed_since only** reject mixed clocks in the candidate proven here. | Constructors do not validate or discover clock provenance. `.after` is static-only for its argument contract; `.seconds` extraction bypasses protection. Keep signed elapsed and existing clocks. E03–E05. |
| Local schedule minute offsets, I12 | Retain validated `HH:MM` strings in config, QTime in editor, `int *_minute_of_day` inside schedule evaluator, `datetime` at the call. | Existing validation and day/window logic; names state local civil-time meaning. | A minute-of-day is not a duration or Unix instant. No wrapper needed for a few local comparisons; no timezone/scheduling policy change. E05. |
| Progress, rail and color fractions, I13 | Retain `float fraction` / `share` locally, existing clamp where already used. | Existing numeric computation and clamp only. | No universal `Fraction01`: historical signed statistics can yield shares outside 0–1; DPR/color/geometry ratios have distinct policies. Wrapping would falsely promise validity and complicate painting. |
| Logical/device pixels, font points, colors, I14 | Retain Qt geometry/color classes and named `int`/`float` locals/constants. Use `logical_x`, `physical_width`, `dpr`, `glyph_px` where crossing scales. | Existing QSize/QRect/QPointF/QColor contracts and explicit DPR conversion. | No numeric interchange protection; immediate framework calls and confined geometry make wrappers costly. Font points and CSS font weights are not pixels. |
| Numeric categorical values, I15 | Distinct internal `IntEnum` families for portal color-scheme and contrast; retain raw response/status/priority integers at their adapter with named constants/maps. Keep existing Qt enums and core state/preference enums. | A plain `Enum` would separate families more strongly; `IntEnum` gives named meanings and checked parameter separation while preserving integer adapters. | `IntEnum` values still compare/arithmetic as integers; validation must precede decoding, unknown/error policy stays. Portal preferences currently have no rendering consumer; enum use must not activate one. |
| IDs, file descriptors, counts, indices and limits, I16–I18 | Retain named primitives and existing owner objects (`SleepInhibitor`, notifier); bounded limits stay integers. | Ownership/error handling and explicit range checks already carry the useful guarantees. | A nominal fd does not close it, distinguish D-Bus fd index from descriptor at runtime or prevent double-close. Wrappers add navigation without meaningful arithmetic safety here. |
| Multi-number data records and wire aliases, I19–I21 | Retain `DailyStatRow`, `TransitionRow`, `LogEntry`, `DurationParts`, CLI `StatusSnapshot`, machine events. Add a GUI-local `DailyChartRow(NamedTuple)` with `label`, `sit_seconds`, `stand_seconds`, `is_today`. Keep wire `Annotated` aliases. | Named fields expose roles; NamedTuple preserves indexing, unpacking, ordering and JSON-array shape. | Same-typed sit/stand positional arguments remain swappable. Wire aliases describe transport signatures, not units; do not replace them with domain types inside decorators. |

The common rule is to introduce a type where meaning must survive a function or
module boundary, an object where operations must depend on the domain, and a
record where positions obscure roles. Retain primitives where a local name and
an immediate arithmetic/framework operation express the contract more directly.
Do not use aliases or blanket casts to claim guarantees they cannot provide.

## Repository-wide inventory

The inventory follows producer, conversion, arithmetic, storage and consumer boundaries.

Evidence E01/E02 covers all 63 production Python files, including unannotated
assignments, literals, arithmetic, comparisons and calls. The AST search produced
2,081 overlapping numeric/unit candidate sites, **not** 2,081 independent semantic
domains. Text review also inspected protocol declarations, comments and named
records that a numeric-literal search misses. The following producer → conversion
→ arithmetic → storage → consumer chains group those sites by contract. Source
links name current symbols; they are the authority over older planning maps.

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

## Representation comparison

| Candidate | Legibility and navigation | Enforced / unsupported | Arithmetic, adapters and maintenance | Decision |
| --- | --- | --- | --- | --- |
| Better names and named parameters | `idle_ms`, `timeout_seconds`, `logical_x` explain a scalar without a jump to another file. Same-type named fields explain records. | Documents intent; checker cannot separate units. | No allocation/serialization cost; best inside short math/framework paths. Existing TOML keys must not be renamed to improve Python names. | Retain for local units, raw config, geometry, fractions, IDs/counts. |
| Type aliases, e.g. `HeightMetres: TypeAlias = float` | Signature advertises meaning; definition lookup still needed to know enforcement. | Alias height and duration remain assignment-compatible; E03 explicitly accepts alias mixing. | Zero adapter cost, ordinary math, but misleading if treated as safety. | Keep aliases for wire/JSON structural shapes; prefer nominal quantities where unit separation is intended. |
| Nominal `NewType` | `move_to(height: Metres)` / `credit(seconds: Seconds)` clearly names shared domain; one small vocabulary to learn. | Rejects incompatible arguments and assignment of erased arithmetic results; **NewType does not validate or convert**. Mixed-unit arithmetic still passes and returns float. E03/E04/E05. | No wrapper allocation; JSON sees underlying float/int. Explicit conversion/rebranding at trusted seams; per-expression branding inside arithmetic is distracting. A branded int remains int at runtime, but a NewType based on float does not promise an actual float payload. | Use for metres, fractional seconds, idle milliseconds and snooze minutes at typed boundaries. |
| Frozen value object | `now.elapsed_since(previous)` expresses an instant operation; bare `.seconds` math loses that benefit. | Named operation can constrain clock statically and with explicit checks at runtime. A dataclass annotation alone does neither validation nor runtime operand enforcement. | Allocation/equality/debug repr changes; JSON/SQLite/Qt need scalar adapters. Full height/length algebra requires many operators and policies. | Use two minimal clock objects with explicit methods. Reject general quantity algebra and a separate object per timeout/pixel. |
| Enum | Named category rather than `if value==1`; distinct families explain same numeric code with different meanings. | Decoder rejects unknowns before enum construction; enum alone does not choose fallback. IntEnum stays numerically compatible; not strong dimensional separation. | Preserve raw ints at external adapters; existing state/preference/Qt enums already work. | Name portal preference codes internally; leave raw open codes at the adapter, keep known constants/maps. |
| NamedTuple / TypedDict / dataclass record | `.stand_seconds` beats tuple position 2; DailyStatRow already proves the pattern. | Field names/types, no automatic validation or prevention of swapping two Seconds values positionally. | NamedTuple preserves tuple and JSON array behavior; dataclass/object needs adapters. TypedDict preserves dict shape, but no runtime validation. | Retain current decoded records and CLI snapshot; add one chart NamedTuple with keyword construction. |

Nominal quantities intentionally trade full dimensional enforcement for ordinary
expressions. In `_classify`, `(sit + stand)/2` is readable as local arithmetic;
in `_cycle_state_for_height`, `abs(height-preset) <= tolerance` is the domain
rule itself. Expanding both into an absolute-height/delta-height algebra would
require addition/subtraction/comparison overloads, midpoint helpers, casts and
serialization adapters for little benefit at this scale. Clock differences have
a different risk: subtracting unlike clocks has no meaningful result, so a named
operation earns the object and its runtime check.

## Before and after examples

“Before” excerpts below reflect current identifiers and expressions, sometimes
with surrounding orchestration omitted. “After” examples show proposed contracts,
not installed code or a complete patch. E03–E05 exercise the selected nominal,
clock, conversion and serialization contracts; they do not type-check every
illustrative call chain or a migrated application.

### Desk, configuration, display and tolerance

Current chain: BLE/MockDesk → DeskPort → StateMachine/Daemon → Desk1 double →
DaemonClient float / CLI StatusSnapshot → Formatter. Commands reverse the height
path; CLI movement selects names/gestures, not numeric heights.

```python
# Before: desk/port.py and core/display_prefs.py
async def get_height(self) -> float | None: ...
async def move_to(self, height: float) -> bool: ...
def from_display_height(value: float, unit: HeightUnit) -> float:
    if unit == HeightUnit.INCHES:
        return value * METRES_PER_INCH
    return value / 100

# Before: core/machine.py
midpoint = (self._preset_height(DeskState.SITTING)
            + self._preset_height(DeskState.STANDING)) / 2
if abs(height - self._preset_height(state)) <= tolerance:
    return state
```

```python
# After: shared core vocabulary; corresponding domain interfaces
Metres = NewType("Metres", float)
async def get_height(self) -> Metres | None: ...
async def move_to(self, height: Metres) -> bool: ...
def from_display_height(value: float, unit: HeightUnit) -> Metres:
    if unit == HeightUnit.INCHES:
        return Metres(value * METRES_PER_INCH)
    return Metres(value / 100)

# Arithmetic stays the same; its result is an ordinary float.
midpoint = (self._preset_height(DeskState.SITTING)
            + self._preset_height(DeskState.STANDING)) / 2
if abs(height - self._preset_height(state)) <= tolerance:
    return state

# A config consumer can brand after existing loader/save validation:
tolerance = Metres(self._cfg.advanced.movement_tolerance)
# A Qt binding/wire adapter still passes a primitive:
self._async_call(IFACE_DESK, "MoveToHeight", float(height))
# Desk1.MoveToHeight keeps DBusDouble and adapts to Metres internally.
```

`to_display_height` should take Metres and return a float paired with HeightUnit.
The displayed number needs its unit argument/context; creating a single nominal
“DisplayHeight” would not distinguish cm from inches. The inverse must perform
conversion before branding. `Metres(110)` is not 110 cm and is not checked against
the desk range. Domain type does not replace `_preset_height`/`_validate` or the
daemon's save/movement policy. CLI snapshot height can become Metres internally,
but its raw 0 wire sentinel must be handled before presentation as today.

### Accounting, idle milliseconds, whole seconds and minutes

```python
# Before: ActiveTimeAccounting.account
elapsed = now - last_observation
idle_threshold_ms = idle_threshold_seconds * 1000
if not (0 <= elapsed <= TIME_JUMP_THRESHOLD_SECONDS) or absent or idle_ms >= idle_threshold_ms:
    self._pending_credit.clear()
elif idle_ms / 1000.0 < elapsed:
    self.flush()
    self._stats.add_active_time(state, elapsed)

# Before: StateMachine.snooze; GUI AutomationPage._apply
self.snooze_until = now + minutes * 60
cfg.automation.sit_duration = self.sit_dur.value() * 60
```

```python
# After: explicit fractional conversion; preserve config's integer type
def milliseconds_to_seconds(value: Milliseconds) -> Seconds:
    return Seconds(value / 1000)

def minutes_to_seconds(value: Minutes) -> Seconds:
    return Seconds(value * 60)

elapsed = now.elapsed_since(last_observation)  # signed Seconds
idle_threshold_ms = idle_threshold_seconds * 1000  # local numeric comparison
if not (0 <= elapsed <= TIME_JUMP_THRESHOLD_SECONDS) or absent or idle_ms >= idle_threshold_ms:
    self._pending_credit.clear()
elif milliseconds_to_seconds(idle_ms) < elapsed:
    self.flush()
    self._stats.add_active_time(state, elapsed)

self.snooze_until = now.after(minutes_to_seconds(minutes))
cfg.automation.sit_duration = self.sit_dur.value() * 60  # still int seconds
```

Brand pending-credit sum at the point it re-enters a Seconds field/API, rather
than asserting every intermediate sum is already Seconds. Config's whole-second
fields remain plain ints; consuming code can explicitly form `Seconds(value)`.
Minute editor `//60` floors, while variation rounds the allowed range up to whole
minutes. Neither is interchangeable with accounting fractional division. E05
checks 1500 ms → 1.5 s, minute conversion and existing zero/positive validation.

### logind microseconds and Unix log timestamps

```python
# Before: SleepInhibitor._learn_max_delay
if isinstance(microseconds, int) and microseconds > 0:
    self._max_delay = microseconds / 1_000_000
# Before: core/journal.py
entry_timestamp = int(raw.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000

# After: raw integer unit stays visible at each isolated external adapter
if isinstance(microseconds, int) and microseconds > 0:
    self._max_delay = Seconds(microseconds / 1_000_000)
entry_timestamp = UnixInstant(
    int(raw.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000)
# Existing decoder/renderer validity policy still runs; object .seconds is
# emitted into LogEntry/JSON, or stored in a typed internal instant field.
```

The same scale conversion produces two different kinds, an allowance and an
instant. Preserve inhibitor headroom/floor/ceiling/fallback exactly. In particular,
its current `isinstance(int)` check also accepts bool; nominal types must not
silently tighten this while other adapters explicitly reject bool. Future policy
changes need separate authorization. E05 proves the formula, not live logind.

### Wall instants, monotonic receipt stamps and countdowns

```python
# Before: machine/accounting wall observation and Overview interpolation
time_elapsed = now - self._last_check
is_time_jump = not (0 <= time_elapsed <= TIME_JUMP_THRESHOLD_SECONDS)
self._progress_stamp = time.monotonic()
elapsed = time.monotonic() - self._progress_stamp
shown = max(0.0, self._remaining - elapsed)
```

```python
# After: each class has its own same-clock method (candidate proven E03–E05)
@dataclass(frozen=True)
class UnixInstant:
    seconds: float

    def elapsed_since(self, earlier: "UnixInstant") -> Seconds:
        if not isinstance(earlier, UnixInstant):
            raise TypeError("UnixInstant required")
        return Seconds(self.seconds - earlier.seconds)

    def after(self, duration: Seconds) -> "UnixInstant":
        return UnixInstant(self.seconds + duration)

# MonotonicInstant has the analogous implementation using its own class.
time_elapsed = now.elapsed_since(self._last_check)
is_time_jump = not (0 <= time_elapsed <= TIME_JUMP_THRESHOLD_SECONDS)
self._progress_stamp = MonotonicInstant(time.monotonic())
elapsed = MonotonicInstant(time.monotonic()).elapsed_since(self._progress_stamp)
shown = max(0.0, self._remaining - elapsed)
```

The runtime mixed-clock rejection established by the final proof is specifically
`elapsed_since` in both directions. It does **not** establish a general runtime
unit system, validate `.after` arguments, detect a float from the wrong clock
wrapped in the right class, or prevent extraction/mixing of `.seconds`. No
operator-overload promise is needed. A simpler frozen record with no explicit
checks would offer only static protection for these methods. The earlier timing
prototype's annotations alone did not prove runtime mixed-clock rejection.

### Local schedules and decoded/chart records

```python
# Before: core/schedule.py
start = _minutes(config.start)
end = _minutes(config.end)
now_min = when.hour * 60 + when.minute
# Before: StatisticsPage._refresh / DailyBarsChart
rows.append((label, sit, stand, window_day == end_date))
label, sit, stand, _ = self._rows[index]

# After: local names stay primitive; these are civil-time offsets
start_minute_of_day = _minutes(config.start)
end_minute_of_day = _minutes(config.end)
now_minute_of_day = when.hour * 60 + when.minute

class DailyChartRow(NamedTuple):
    label: str
    sit_seconds: float
    stand_seconds: float
    is_today: bool

rows.append(DailyChartRow(label=label, sit_seconds=sit,
                         stand_seconds=stand, is_today=window_day == end_date))
chart_row = self._rows[index]
sit = chart_row.sit_seconds
stand = chart_row.stand_seconds
```

Field types could be Seconds when the chart interface adopts the shared domain
vocabulary; field **names** provide the sit/stand distinction either way. Existing
DailyStatRow and TransitionRow already preserve tuple-indexing and JSON arrays;
retain them instead of adding a second decoded-row hierarchy. A NamedTuple's
tuple equality/indexing/unpacking is useful compatibility, but positional
construction can still swap two same-typed values. Use keyword construction at
the ambiguous producer. E05 directly verifies the current DailyStatRow JSON
shape; it does not claim a newly implemented chart record.

### Geometry, fractions, codes and handles

```python
# Before and recommended arithmetic: HeightRail._x; naming can clarify px
span = self.width() - 2 * self._PAD
frac = (meters - self._lo) / (self._hi - self._lo)
logical_x = self._PAD + _clamp01(frac) * span

# Before: selectable_icon.render; recommended names at scale conversion
physical_width = round(box * dpr)
canvas = QPixmap(physical_width, physical_width)
canvas.setDevicePixelRatio(dpr)

# Proposed internal preference vocabulary, after existing int validation
class PortalColorScheme(IntEnum):
    NO_PREFERENCE = 0
    DARK = 1
    LIGHT = 2
# Contrast needs its own family; it is not another color-scheme quantity.
```

Keep ratio/fraction arithmetic local; E05 exercises a metre ↔ fraction ↔ logical
position inverse without a Qt application. Keep the inhibitor's existing named
`descriptor` and owner class: `granted = spares.pop(int(reply.body[0]))` converts a
**D-Bus array index** into an fd. Branding both numbers would neither establish
ownership nor replace spare cleanup; a generic numeric wrapper would obscure the
important conversion. Code0 versus None must remain distinct wherever absence is
optional. These primitive decisions follow from the complete call paths rather
than a rule that every `float`/`int` needs a class.

## Compatibility implications

| Boundary / policy | Existing contract to preserve | Consequence of the recommendation |
| --- | --- | --- |
| TOML and mutable config | Existing keys, duration strings/raw integer input, int/float distinctions, bool exclusion where already enforced, preset slack/round4, comments/unknown data preservation, default values and migrations. `_apply_section` consults `type(getattr(target,key))`, not annotations. | Leave config scalar storage primitive. A NewType annotation alone does not change default/load values; an object default changes expected runtime type and would break inference. Explicit validated domain adapters avoid this. Saver's direct writes and format_duration_compact must still receive original scalar kinds. No “strict quantity” rewrite of config validation. |
| Zero/negative values | sync0 disables normal sync, variation0 no random addition, threshold0 has current gating meaning, target0 unconfigured/unseeded; discover0 cache-only; height0 unknown on wire; snooze0 absent/pending; idle0 active/failure-open; singleShot0 queued work. Lead time/linger do not share all automation positivity checks. | Do not encode a global positive duration/height/timestamp invariant. Retain internal optional height/snooze where already present; adapt to original wire zero. A broad None migration would be an API/policy change. |
| SQLite | daily.seconds REAL; transitions.ts REAL; interrupted INTEGER; schema_version1 and fail-soft behavior. Historical finite negative/zero daily values and locally renderable negative/zero timestamps remain usable. | Unwrap clock objects and nominal scalars before binding. No schema, migration, row order, precision or historical cleanup. Seconds represents signed values; accounting plausibility is a separate rule. No blanket rounding of fractional active time. |
| JSON and named rows | Daily/transition arrays keep order, length prefixes and open text; logs are dicts with raw numeric params and legacy fallback. | NewType retains scalar serialization. Clock/height dataclasses need adapters; `asdict` changes shape and cannot be silently substituted for scalar/array JSON. Existing NamedTuple rows remain valuable. E05 checks both primitive continuity and object adapter cost. |
| D-Bus | DBusDouble d heights/timing; i snooze/discover/limits, u warning seconds; dd progress, su warning, dsssss log; JSON strings for container interoperability. | Preserve decorated annotations, signatures, names, scalar kinds, JSON shapes and error behavior; decode/brand inside domain entry points and unwrap before transport. `DBusDouble` does not distinguish metres from seconds. No domain object directly in emitted property/signal tuple. |
| Qt boundary | Signal(float) heights/snooze, Signal(float,float) progress, primitive slots, QVariant/QDBusMessage extraction, int ms timeouts. | NewType runtime erasure cannot make `.connect` enforce semantic signatures. Dynamic Qt emission, generic `*args`, Any payloads or untyped callbacks weaken static protection. Decode once in a named typed adapter/callback; preserve primitive signals or use a separately typed internal callback. Avoid blanket cast: it asserts trust rather than checking/converting. No bus/signal integration was run for this assessment. |
| Desk/library input | External scalar height metres, notification raw binary offset conversion, optional read failure, bool move result only command success, linger/retry/grace/timeouts in seconds. | Brand at port adapter, unwrap at library call; preserve read-back tolerance/interruption handling and external library contract. A Metres value is not evidence of arrival or validated physical range. No library install or live BLE check. |
| Idle/logind/journal | Provider-specific ms interpretation and assume-active fallback; logind allowance µs with current filter/fallback/clamp; journal timestamp µs with current decode/error policy; fd index distinct from owned fd. | Named conversions preserve unit and precision; types cannot repair external provider semantics or prove fd ownership. Do not normalize KDE policy to specification units during typing. |
| Local schedule | Local datetime, weekdays, overnight belongs to start day, equal bounds full24h, HH:MM config, display-hour preference independent. | Keep civil-time representation and evaluator; no conversion to duration/epoch, timezone-aware scheduler or new DST rule. Existing local clock/DST behavior stays. |
| Wall jumps and suspend | Machine uses wall seconds to recognize backward steps or elapsed beyond TIME_JUMP_THRESHOLD_SECONDS (300s) and reset accumulation; accounting discards implausible pending credit; snooze uses wall deadline; scan-cache age is wall-derived. | Types label the present clock rather than selecting a new one. Keep signed elapsed so backward jumps reach current detection. A positive-only duration object would break it. Do not switch scan cache/accounting/snooze to monotonic as part of typing. |
| Monotonic, GUI interpolation and sleep waits | BLE awake grace, height throttle, daemon overrun and GUI receipt stamps use monotonic; asyncio owns relative waits; explicit pre-sleep disconnect/inhibitor path exists independently of wall jump detection. | Keep clock sources/deadlines. Do not treat all monotonic clocks as suspend-inclusive boottime or assume every platform counts suspend the same way. Repository comments record linger wait preserving remaining interval across freeze; this assessment did not remeasure it. GUI countdown ages from receipt, not an epoch transferable between processes. No new suspend resync/interpolation policy. |
| Python/internal compatibility | Primitive equality, repr, serialization and numeric operations currently work; optional fields and typed events already carry meaning. | NewType keeps runtime values; explicit clock objects change in-memory equality/repr/operation syntax and require all relevant producers/consumers adapted together. Existing tests relying on floats would require focused updates in an authorized implementation. No production migration or performance claim is established by these small probes. |

An authorized implementation would require a small shared Qt-free vocabulary,
typed port/algorithm signatures, explicit clock producers and operations, config/
wire adapters, field-level decoder annotations, and a GUI-local chart record.
Runtime class checking belongs only in the named clock operation whose guarantee
is intended. This identifies the complete consequences together; it neither
authorizes implementation nor schedules additional domain assessments.

## Focused static and runtime evidence

All verification below was executed freshly for this report. Earlier exploratory
receipts are not final evidence. Stable evidence IDs resolve to the quick-local
`261020-e17-EVIDENCE.md`; its probe pointer locates temporary source/receipt files.

| Evidence ID | Command / scope | Recorded outcome and supported claim |
| --- | --- | --- |
| E01 | Sorted regular-file list and SHA-256 manifest for src/, tests/, AGENTS.md, TODO.md. | 453 files at baseline; final list/hash gate passes. Includes preexisting dirty AGENTS.md/TODO.md bytes. |
| E02 | Temporary inventory.py parses all production Python; rg/text review follows producers, conversion, arithmetic, fields, storage and consumers. | 63 files / 2,081 overlapping candidate sites. Inventory includes unannotated sites, records, Qt/external declarations and contextual primitive exceptions. This is source assessment, not proof of every runtime path. |
| E03 | Final `run_probes.py --repo-root . --receipt ...` positive branch: cached `python -m mypy`, project config, **mypy 2.3.0**, actual repository virtualenv path retained. | Exit0 for positive.py/model.py: deliberate nominal conversion and same-clock methods accepted; aliases and nominal mixed arithmetic also accepted, proving their limits. No global application type-check claim. |
| E04 | Same runner, expected negative branch. | Exit1 with exactly9 normalized `(file,line,code,message)` diagnostics matching the complete expected list, zero unexpected. Covers Seconds→Metres, displayed float→Metres, ms/min→Seconds, both mixed-clock elapsed directions, instant used as duration, and assigning erased arithmetic to Metres. Intentional type failures are proof success, not tool failure. |
| E05 | Same runner, runtime.py under existing .venv; no Qt/bus/desk objects. | Exit0, 25 named assertions: cm/in conversion, fractional ms/min, µs budget formula, nominal arithmetic/identity/nonvalidation/nonconversion, JSON scalars/rows/object adapters, signed wall elapsed and monotonic deadline, both explicit mixed-clock runtime checks, config zero/positive rules, signed history, integer grammar/fractional display, overnight schedule, geometry inverse. |
| E06 | Plan's three automated gates (Task2/Task3 rerun every final example), source links and protected-tree checks. | Pass on final report/evidence tree. Zero new or expanded tests; zero retained repository probe scripts. See local ledger for commands and hashes. |

To reproduce from the checkout root while scratch evidence is retained:

```sh
probe_dir=$(cat .planning/quick/261020-e17-assess-semantic-types-across-numeric-bou/261020-e17-PROBE-DIR.txt)
.venv/bin/python "$probe_dir/run_probes.py" --repo-root . --receipt "$probe_dir/receipt.json"
sha256sum --check .planning/quick/261020-e17-assess-semantic-types-across-numeric-bou/261020-e17-READONLY.sha256
```

The runner records executable versions, argv, each exit code/output, exact
expected/actual/unexpected diagnostics, runtime assertion names, and SHA-256 maps
for itself, probe/config inputs and 11 grounding production sources. It writes the
receipt atomically; any version/diagnostic/assertion mismatch fails the gate.
`--repo-root` supplies every checkout path; no checkout absolute path is embedded
in the runner. The cached checker executable is scratch configuration, and
`--python-executable` preserves `.venv/bin/python` spelling rather than resolving
the virtualenv symlink. Bytecode/checker caches stay in /tmp or are disabled.

These results establish the behavior of bounded candidates and actual pure
conversion/validation/decoder helpers. They do not prove a migrated application,
wire reflection accepting new annotations, Qt signal static safety, live external
units, hardware behavior, performance or platform suspend semantics. No such
claim is necessary to decide where clearer intent justifies a type.

## Evidence retention audit

Retain E01 manifests, E02 inventory/method counts and E03–E06 command/outcome
ledger locally under the quick task; retain only this assessment as the tracked
deliverable. Final runner, models, positive/negative/runtime probes, AST inventory,
private caches and atomic receipt live in the temporary directory named by
`261020-e17-PROBE-DIR.txt`:
`/tmp/idasen-semantic-assessment-z2mwrk4h/semantic-types-final.0AsfCe`.

Historical `/tmp/idasen-quantity-explore-w9r1pld7` inputs read only as hypotheses:
aliases.py, nominal.py, limits.py, value_objects.py, value_object_operators.py,
timing.py; positive-receipt.json, negative-receipt.json, runtime-receipt.json,
timing_positive-receipt.json and timing_negative-receipt.json. None substitutes for
the final runner. In particular the earlier timing receipt established static
rejection, not runtime mixed-clock rejection; E05 supplies the narrow explicit
runtime check now described.

The final protected file list matches byte-for-byte and all 453 hashes pass.
There are **zero new or expanded tests, zero removed tests, zero repository probe
scripts retained**. The temporary research cases intentionally cover distinct
type/conversion/compatibility contracts, not a Cartesian product to maintain in
the permanent suite. No full suite was run: the result changes documentation
only, and the relevant checks are source anchors, bounded proofs and file
preservation. No application/daemon/test instance was launched, inspected,
stopped, restarted or killed; no hardware/session-bus, package install, remote
Git, release or unrelated capture action was performed. Future deletion of /tmp
will remove executable proof inputs; the tracked document remains the durable
decision, while the local receipts/manifests are reproducibility evidence rather
than a promised permanent test harness.
