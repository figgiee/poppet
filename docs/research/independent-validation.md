# Independent validation — public Cascadeur-MCP implementations (2026-10-26)

Re-validation of the landscape **without relying on our earlier survey notes**: each
public repository was cloned at its current default branch, recorded by commit, and
statically inventoried for tool registrations and architecture markers. Our own server
was validated dynamically instead (MCP `tools/list` + a live capability run), which is
the stronger direction of evidence.

Raw scan: [`landscape-scan-2026-10-26.json`](landscape-scan-2026-10-26.json) ·
scanner: [`scripts/independent_validation.py`](../../scripts/independent_validation.py)

## Method

1. `git clone --depth 1` each repo; record `HEAD` SHA and last commit date.
2. Static scan (read-only, nothing executed): regex inventory of MCP tool
   registrations (`@*.tool`, `Tool(`, `add_tool(`, `register_tool(`), README-declared
   tool counts, and architecture markers (`8765`, `run_script`, `user_scripts`,
   `QTimer`/PySide, "Python Console", `start_bridge`/`start_mcp`, safety markers such
   as allowlist/ACL/dry-run, tests present).
3. Ours: **dynamic** count through the real MCP stdio transport
   (`tools/list` → 45 tools) plus the 45/45 live capability proof
   ([docs/proof/](../proof/README.md)).

**Limitations, stated up front:** competitor tool counts are static-heuristic or
README-declared, not executed; decorator counts over-count client wrappers in some
repos and miss dict-based registries in others (MnxD2A6 registers tools through a
registry, so its 5 decorator hits understate it). No side-by-side runtime benchmark was
run: every competitor needs its own Cascadeur-side bridge/install, and loading several
bridges into one live Cascadeur session would conflict. The comparison below is
therefore about **architecture, surface, and engineering discipline**, plus the
strength of evidence — not latency.

## Re-scanned repositories

| Implementation | HEAD (this scan) | Last commit | Tools (best evidence) | Reaches Cascadeur via | Safety/limits | Tests |
|---|---|---|---|---|---|---|
| **cascadeur-mcp (ours)** | this branch (`feat/native-script-server`) | 2026-10-26 | **45** — dynamic MCP `tools/list`, 45/45 called live | Native 8765/8766 `run_script` + shipped runtime; optional zero-touch `user_scripts` autostart; console bootstrap otherwise | Digest-stamped runtime, checked modify sessions, 30 s server cap documented | 219 offline tests + 45/45 live |
| [gprethesh/cascadeur-mcp](https://github.com/gprethesh/cascadeur-mcp) | `eb0ca7e2` | 2026-09-15 | 36 (+1 gated) — README | Own Qt-timer mailbox bridge; `start_bridge.py` pasted into Python Console; explicitly refuses the native server | Broad pose/camera/PNG review; no arbitrary Python unless gated | yes |
| [MnxD2A6/cascadeur-mcp](https://github.com/MnxD2A6/cascadeur-mcp) | `fce27036` | 2026-10-09 | 37 — README (registry, not decorators) | Host hook installs startup bridge; private JSON queue with ACLs | Deepest safety: allowlist, rollback/recovery, preflight, alpha | yes |
| [Karylcode/cascadeur-mcp-plus](https://github.com/Karylcode/cascadeur-mcp-plus) | `916b8961` | 2026-10-24 | 27 — README (matches scan) | Native 8765 `/run` bootstraps an in-app HTTP server on :48766 (PySide, 25 ms Qtimer); console-free after first call | UI automation/render/video extras; second in-app server | yes |
| [BrianFinch-1/cascadeur-codex-bridge](https://github.com/BrianFinch-1/cascadeur-codex-bridge) | `cda22272` | 2026-10-18 | not published as a count; documented groups | Authenticated Python bridge daemon + in-app agent; install scripts/ZIPs | Productized: readonly/standard profiles, SHA256SUMS | yes |
| [muhwagwa0112/cascadeur-complete](https://github.com/muhwagwa0112/cascadeur-complete) | `82b350ca` | 2026-10-01 | not published as a count; named tools | `user_scripts` command package + Win32 message-window UI pump | Pre-native architecture (2026.1.3); mocap-cleanup niche | yes |
| [ysk424/cascadeur-mcp](https://github.com/ysk424/cascadeur-mcp) | `725c11e8` | 2026-06-16 | 5 — scan/README | Per-call app launch with `--run-script` external command | Tiny surface, no license file | no |

Scan markers (from the JSON): only ours and Karylcode build on the native 8765
server; gprethesh, MnxD2A6, BrianFinch, muhwagwa and ysk ship their own bridge/agent.
gprethesh and Karylcode require a console step (unless Karylcode's first call can
bootstrap); MnxD2A6 installs a startup host hook; muhwagwa edits `Python.Path`/commands.

## Verdict

- **Surface:** ours (45 dynamic tools) is the largest typed surface; gprethesh (36+1)
  and MnxD2A6 (37) are close, with different specialisations (pose/camera review;
  safety/recovery).
- **Architecture:** ours + Karylcode are the only native-server implementations, which
  keeps the Cascadeur-side surface minimal. Ours adds (a) the interpreter-keeper fix
  required on 2026.2.3, (b) digest-stamped runtime shipping, (c) optional zero-touch
  `user_scripts` add-on, (d) a dynamically verified 45-tool proof.
- **Evidence:** only this project publishes a reproducible live capability proof
  (45/45 tools through MCP, screenshots, FBX round-trip) plus protocol tests run
  against Cascadeur's *shipped* `server.py`. Competitor evidence is README-level.
- **Not claimed:** no runtime benchmark and no independent third-party audit. A
  head-to-head latency/task benchmark would need isolated Cascadeur instances per
  bridge; that is the honest remaining step to call this "best" without qualification.

Bottom line: on **2026.2.3, native-server, typed-tool, evidence-backed** grounds this is
the strongest public implementation found; competitors may beat it on safety posture
(MnxD2A6) or niche workflows (gprethesh pose/camera, muhwagwa mocap cleanup).
