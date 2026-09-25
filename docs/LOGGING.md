# Logging policy

Why this exists: level choices in this app kept needing individual argument.
Per-attempt BLE errors sat at `debug` even though they *are* errors;
`MoveFailed` had to be promoted to `warning`; the BlueZ snapshot landed at
`warning` after a debate. Each was settled on its own, and none of the
arguments generalized to the next line.

The reason is that one field was doing two jobs. `debug/info/warning/error`
was being used to answer *how bad is this* **and** *who is this for*, and those
two questions have different answers. A BLE connect retry that later succeeds
is genuinely a warning — it just isn't a warning **for the person wondering why
their desk moved**. With only one dial, "not for that reader" had to be spelled
`debug`, which then also meant "not important", which it wasn't.

So: **audience is its own axis.**

## The three axes

Every log line has a **channel** (who), a **level** (how bad), and — on the
activity channel — a **message id + params** (what, in a form that can be
re-rendered in another language).

### Channel: who is this for

| Channel | Reader | Question it answers |
| --- | --- | --- |
| `activity` | the person using the desk | "Why did my desk do that?" |
| `diagnostic` | whoever is reading a bug report | "Why isn't this working?" |

This is the split [Windows types its event channels
by](https://learn.microsoft.com/en-us/windows/win32/wes/defining-channels)
(Admin — end users, "a problem and a well-defined solution" — versus
Operational and Debug), and the one the [Nextcloud desktop
client](https://docs.nextcloud.com/desktop/3.11/navigating.html) ships in
product form: an Activity view for what happened to your files, a separate
`--logwindow` for the Qt-level output you attach to a bug.

The test for `activity` is not "is it interesting" — it's **would this change
what the user thinks is going on with their desk, or what they'd do next?**
"No idle-time provider is available, so the desk will move whether you're here
or not" is activity: it changes what the app will do to you. "Idle provider:
Mutter" is diagnostic: same behavior either way, it just says which code path
got there.

Both channels go to journald, always. The GUI's Activity Log shows `activity`
by default and `diagnostic` on request. Nothing is silently dropped — the
channel decides *prominence*, not *existence*.

### Level: how bad is this

Levels now mean the same thing on both channels, because they no longer have
to encode the audience:

| Level | Meaning |
| --- | --- |
| `error` | The app cannot do the thing and will not retry on its own. |
| `warning` | Something failed or is degraded. Automation may still work. |
| `info` | Normal operation worth a line. |
| `debug` | Step-by-step detail; noisy by design, off unless asked for. |

The cases that used to need arguing now fall out:

- **Per-attempt BLE errors** → `diagnostic` / `warning`. They *are* warnings.
  Putting them on the diagnostic channel is what keeps them out of the user's
  feed, so they no longer have to be mislabelled `debug` to stay out of it.
- **`MoveFailed`** → `activity` / `warning`. The desk didn't move. That is the
  single most user-facing failure the app has.
- **The BlueZ snapshot** → `diagnostic` / `warning`. It exists so a repeat
  outage diagnoses itself; it means nothing to a desk user.

### Message id: what happened

Activity lines carry a stable id and raw parameters, not a finished sentence:

```
id     = "cycle.reset.idle"
params = {"next_target": 1500}
```

The daemon renders English from the catalog for journald — stable and
greppable, which is what bug reports need. The GUI receives the id and the
params and composes its own sentence with `tr()`, so the Activity Log
translates like every other string in the app. This is
[systemd's `MESSAGE_ID` + catalog
design](https://systemd.io/CATALOG/), adopted for the same stated reason:
"provide native language explanations for English language system messages".

**Parameters are raw values, never pre-formatted strings.** `{"next_target":
1500}`, not `{"next_target": "25.0 minutes"}` — the second cannot be
localized, which defeats the point.

### The journal's duration wording changed

Before this note existed, a `Param.DURATION` value rendered two different
ways for the same log event: journald read `"45.0 minutes"` (or
`"30 seconds"` under a minute), while the GUI's Activity Log — reading the
same id and the same raw seconds — showed `"45m"`. That split is now closed:
the journal renders the same compact shape the Activity Log always has,
`"30s"` / `"45m"` / `"1h 05m"`. **If a grep or a log-parsing script matches
the old `"45.0 minutes"` / `"30 seconds"` shape, it needs to match the
compact one instead.**

Diagnostic lines may stay free-form English. They are never translated (they
exist to be pasted into a bug report), so requiring a catalog entry for each
one would be pure overhead.

## Rules

These are the ones that were being decided ad hoc. They are rules now, and
where a rule is mechanically checkable there is a test named after it.

### 1. A line that changes when the desk will next move must say when

The trailing "Next change after 25m of active time." is not decoration. It is
the answer to the only question the Activity Log exists to answer, and any
line that resets the clock without it tells the user their schedule moved and
declines to say where.

This used to be attached per-call-site, so it appeared on the five events that
happened to carry a duration and was missing from every event that *reset the
accumulator* — coming back from idle, waking from suspend, a detected time
jump, returning to your session. Those are exactly the lines that most need
it.

Enforced by `tests/test_log_messages.py`, which drives every cycle-restarting
event through the daemon and asserts the note is present.

### 2. The activity channel records changes, not requests

A no-op is not an event. `reload_config` used to write "Configuration
reloaded." unconditionally, and since the GUI nudges the daemon on every Save
whether or not the file changed, one morning's log held 163 identical lines
saying nothing.

A reload that changed nothing is `diagnostic` / `debug` — it did happen, and a
developer chasing "did my config reach the daemon?" wants it. It is not
activity, because nothing about the desk changed.

The same diff decides whether the cycle target is re-rolled, which is what
stops N no-op saves from re-randomizing the current cycle N times.

### 3. Say the resulting state, not just the event

Rule 1 is the specific case of a general one: a line reporting a change should
name what it changed *to*. "Resetting timers" is a fact about the past;
"resetting timers, next change after 25m" is something the reader can act on.
Applies to any new line reporting a state change.

### 4. Level is about severity only

If you find yourself picking a level to control *visibility*, you want the
channel instead. That instinct is the bug this document exists to fix.

## Where lines live

- **journald** — everything, both channels, always English. The full record;
  `journalctl --user -t idasen-companion`. Filter on the *identifier*, not the
  unit: `-u idasen-companion` covers only the daemon's cgroup and so omits the
  lines the GUI writes itself (autostart toggled while the daemon is down).
- **The GUI Activity Log** — seeded from journald on open (so it survives a
  daemon restart, which the old in-memory-only ring did not) and appended live
  over D-Bus. Filterable by channel and level.
- **The in-memory ring** (`daemon/ringlog.py`) — the live tail, and the
  backlog for a GUI that opens while the daemon is running.

There is no second on-disk store. journald already persists this, indexes it,
and rotates it; adding a database to re-implement that would be worse in every
respect.

### Actions taken while the daemon isn't running

Enabling autostart from Settings, or from the "not running" banner, is a real
change to system state made at a moment when the component that owns the log
is by definition not up. The GUI writes those lines to journald itself, under
the same ids, so they appear in the Activity Log in order alongside everything
else.

## Adding a line

1. Which reader? → channel. If it doesn't change what the user thinks their
   desk is doing, it's `diagnostic`.
2. How bad? → level. Independently of step 1.
3. `activity` → add a catalog entry in `core/logmsg.py` with raw params, and
   the matching `QT_TRANSLATE_NOOP` entry in `gui/log_catalog.py`. A test
   asserts the two agree, so drift fails the build rather than silently
   shipping an untranslated line.
4. `diagnostic` → a plain English string is fine.
5. Does it change when the desk next moves? → it must carry `next_target`
   (rule 1).
6. Translate the new string for every shipped language before committing —
   see `CONTRIBUTING.md` § Translations.
