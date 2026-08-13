---
name: Bug report
about: The desk did something you didn't expect, or the app misbehaved
title: ""
labels: bug
assignees: ""
---

**What did the desk (or the app) do, and what did you expect instead?**

**Version and install method**

Which version, and did you install the RPM from a release or build it
yourself? The daemon writes its version into the first line of its startup
log, if you're not sure.

**Desktop and session**

Desktop (KDE / GNOME / other), and X11 or Wayland? Idle and lock detection
differ per desktop, and a mismatch there is the single most common source of
"it moved while I was away" — this is usually the first thing that explains a
report.

**Logs**

```
journalctl --user -t idasen-companion --since "1 hour ago"
```

Filter on the **identifier** (`-t`), not the unit (`-u`) — `-u` only pulls the
daemon's own cgroup and misses the lines the GUI writes itself, so a `-u`
capture is usually missing half the story.

**For Bluetooth problems**

The daemon logs a BlueZ snapshot every time a connect fails (adapter
powered/scanning, device connected/paired/RSSI, other daemons running).
Please paste it — it usually answers the question on its own.
