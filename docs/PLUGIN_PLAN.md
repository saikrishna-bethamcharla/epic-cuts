# Editor plugin plan (M8)

Nothing here is built yet. It exists so M2-M7 do not close any door.

## What the plugins need from the engine

A **local service** the panel can call, independent of the CLI:

| Call | Input | Output |
| --- | --- | --- |
| `order` | paths | ordering report |
| `analyze` | paths + settings | Cut List |
| `export` | Cut List + format | written file path |
| `progress` | — | streaming events (clip, percent, ETA) |
| `cancel` | — | acknowledged cancellation |

Transport: JSON-RPC over stdio for the bundled-engine case, or HTTP on
`127.0.0.1` with a per-session token. Both are thin adapters over the same
functions the CLI calls; progress and cancellation are engine features, not CLI
features, so they must exist from M2 even if the CLI ignores them.

## Premiere Pro (primary panel)

- **Technology:** UXP panel (HTML/CSS/JS). Premiere's UXP support is the current
  path; CEP is the older alternative and Adobe has been retiring it.
- **Flow:** read the selected bin items → send their paths to the local engine →
  receive the Cut List → apply cuts to the active sequence through Premiere's
  timeline scripting API.
- **Fallback that always works:** the engine writes `xmeml` and the user imports
  it. This path is implemented in M4 and stays supported even after the panel
  exists, because it needs no scripting permissions at all.

### Risks to verify before writing code (brief section 13)

These are **not** assumed to be true; each must be confirmed against current
Adobe documentation and a real Premiere build:

1. Which Premiere versions expose sequence/`TrackItem` editing through UXP, and
   which require a host-specific API module.
2. Whether a UXP panel may read arbitrary filesystem paths, or only paths the
   user grants (this decides whether the engine can be handed a bin path).
3. Whether audio-only edits and per-track insert edits are permitted, which
   decides if crossfades can be applied by the panel or must come from xmeml.
4. Adobe developer registration requirements, review turnaround and whether a
   local-only (no network) panel needs a manifest permission declaration.

## DaVinci Resolve

- FCPXML 1.9+ import covers most cases; Resolve's importer is the practical
  target for M4.
- Resolve also has a Python scripting API, which needs the engine to run inside
  Resolve's interpreter environment — a later option, not the first one.

## Final Cut Pro

- FCPXML import (M4). A Workflow Extension is possible later but requires a
  signed host app, so it is out of scope for the first release.

## Packaging and distribution

- **Engine binary:** ship per-OS (M6 single-file executable). The panel launches
  it on demand and talks stdio; no installer daemon.
- **macOS:** the host app and any bundled binary need a Developer ID signature,
  hardened runtime and notarisation, otherwise Gatekeeper blocks the panel's
  helper.
- **Windows:** Authenticode signing for the executable and the installer, or
  SmartScreen will warn on every install.
- **Auto-update:** the panel must never update the engine silently mid-session.
  Check for updates at launch, download, and apply on restart.
- **Adobe Exchange:** submission needs a manifest, icons, a privacy statement and
  a support URL. Requirements change; re-read them at M8 rather than trusting
  this document.

## Sequencing

1. M2-M4: engine + Cut List + exports (no plugin code).
2. M7: local service + review UI, which also proves `progress`/`cancel`.
3. M8: Premiere UXP panel against that service, with the xmeml import path kept
   as the always-available fallback.
