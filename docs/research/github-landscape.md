# Cascadeur MCP landscape — public implementations vs. cascadeur-mcp

Snapshot date: **2026-10-26**. The `cascadeur-mcp` row below describes the pre-1.0
2025.3.3 file-queue design; for the current 1.0 state and a fresh HEAD-by-HEAD
re-validation see [independent-validation.md](independent-validation.md). Research-only survey of every public Cascadeur MCP
implementation found, plus the vendor's built-in server, compared against cascadeur-mcp's
current design and re-evaluated against the fact that Cascadeur **2026.2 now ships a
built-in MCP script server**.

## Method / coverage

GitHub REST search: `q=cascadeur-mcp` → 8 repos; `q=cascadeur mcp` → 9; `q=cascadeur
run_script` → 0; `topic:cascadeur` → 5. Metadata via `api.github.com/repos/...`, READMEs
via `raw.githubusercontent.com`, MnxD2A6's tools via glama.ai; ground truth from the local
`Cascadeur 2026.2.3` server source/README, vendor 2026.2 notes, and AWN/render.ru/LinkedIn.
**Not found:** any Reddit/YouTube/Discord coverage of the native server, and no other
public wrapper of native `8765` besides Karylcode. Stars/dates as of 2026-10-26.

## (a) Comparison table

| Implementation | Transport | How code reaches Cascadeur | Tool inventory | Targeted version | Activity | Verdict |
|---|---|---|---|---|---|---|
| **Cascadeur built-in script server** (vendor) | HTTP JSON-RPC subset on `127.0.0.1:8765`: `GET /health`, `POST /run`, `POST /mcp` | Ship-in: `Scripts → MCP → Start script server`; scripts run on next `scene_idle` with `csc`/`scene`/`app` in scope | **1 tool** (`run_script(code)`) + 2 resources (`cascadeur://docs/python-api`, `cascadeur://modules`); protocol string `2024-11-05` | 2026.2+ (installed 2026.2.3, server v0.3.1) | Vendor product, first shipped Aug 2026 | **Substrate.** Raw Python execution only: no typed tools, no auth, 30 s cap. Every 2026.2-era server sits on it (or bypasses it). |
| **cascadeur-mcp** — [figgiee/poppet](https://github.com/figgiee/poppet) | MCP **stdio** (FastMCP) + file queue (`request<uuid>.json`/`response<uuid>.json`) | Cascadeur-side `user_scripts` install; queue drained on `scene_activated`/`scene_opened` or `Commands → cascadeur-mcp → Process Pending` | **43 tools + 1 resource** (scene/rig/keys/telemetry/AutoPosing/AutoPhysics/FBX/layers/export/selection/undo…) | **2025.3.3** (public snapshot) | 0★, 0 forks; created 2026-05-24, last push **2026-05-25** (pre-2026.2) | **Differentiated but stale.** Deepest verified `csc` coverage in the field; transport obsolete since the native server shipped. Must re-target 2026.2 or die. |
| [gprethesh/cascadeur-mcp](https://github.com/gprethesh/cascadeur-mcp) | MCP stdio → local JSON mailbox | User runs generated `start_bridge.py` in `Window → Python Console`; a **Qt timer** executes one request at a time on the main thread. Explicitly says **do not start** the built-in MCP server | **36 tools + optional 37th** (`cascadeur_run_script` behind `--allow-scripts`): scenes/projects, rigs/objects, body+finger poses, keys/interpolation, track/frame selection, motion sampling, camera/PNG review, FBX import/export, action catalog (physics/AutoPosing/retargeting/cycles), API discovery | App reporting `inHouse`/API `dev`; requires `PySide6`, i.e. **2026.2-era** (exact version UNVERIFIED) | 7★, 4 forks; created **2026-09-15**, pushed **2026-09-15** | **Strongest competitor on breadth.** macOS-tested, image review via MCP, native-server rejection; per-launch console bootstrap is a UX tax. |
| [MnxD2A6/cascadeur-mcp](https://github.com/MnxD2A6/cascadeur-mcp) | MCP stdio (official MCP Python SDK v1) → private local JSON queue (`%LOCALAPPDATA%\cascadeur-mcp\c01`, ACL-restricted) | `python -m cascadeur_mcp.manage install-host --cascadeur-home … --apply` installs a **startup host hook** that schedules the bridge on Cascadeur's Qt main thread | **37 tools**: capability/ping/scene/object/frame/character/skeleton/rig reads; transform, pose, pose-sequence, hand/finger, keyframe/retiming, playback, snapshot/recovery writes; scene-copy save, license-checked FBX export, preflight/recovery diagnostics | **Cascadeur 2026.2.2**, Windows, Python 3.12 (dev machine only) | 1★, 0 forks; created 2026-09-29, pushed **2026-10-09** | **Deepest safety engineering.** Alpha (`0.5.0a13`), allowlist, no arbitrary Python, write-contract revisions, rollback/recovery. Deliberately not built on the native server. |
| [Karylcode/cascadeur-mcp-plus](https://github.com/Karylcode/cascadeur-mcp-plus) | MCP stdio proxy (stdlib) → **in-app HTTP server** `127.0.0.1:48766` (`POST /mcp`, `GET /health`); **native `8765` `/run` only bootstraps** the in-app server | Proxy starts `start_mcp_plus.py` through native `/run` on first call; in-app server runs on bundled **PySide6**, `QTimer` every 25 ms on the GUI thread, scene-idle for rig/import tools | **27 tools**: 23 grouped-action tools (`scene`, `import_export`, `characters`, `selection`, `rigging`, `pose`, `autoposing`, `timeline`, `keys`, `layers`, `physics`, `cleanup`, `ai_motion`, `render`, `camera`, `display`, `ui_inspect`, `ui_input`, `actions`, `history`, `jobs`, `status`, …) + `run_python`, `batch`, `screenshot`, `video_mocap` | **Cascadeur 2026.2** (tested **2026.2.3**), Windows 10/11 | 1★, 0 forks; created **2026-10-23**, pushed **2026-10-25** (newest) | **Closest to cascadeur-mcp's future shape.** Typed tools on the native server, but still needs Cascadeur-side code + a second in-app HTTP server; UI automation/render/video differentiate. |
| [BrianFinch-1/cascadeur-codex-bridge](https://github.com/BrianFinch-1/cascadeur-codex-bridge) | MCP stdio (dependency-free Node.js 18+) → authenticated Python bridge daemon → Python 3.11 agent on Cascadeur main thread | Install scripts / ready-made Windows ZIPs; agent runs in-app; `readonly` vs `standard` security profiles | Tool count **UNVERIFIED**; documented groups: scene inspection, MMD character analysis (VMD dry-run), Outline hierarchy editing, viewport capture, guarded scene edits with dry-run/commit, diagnostics; **no arbitrary Python** | **Cascadeur 2026.2+**, Windows 10/11 | 2★, 0 forks; created 2026-09-12, pushed **2026-10-18** | **Niche but productized** (ZIP releases, SHA256SUMS, policy profiles). MMD/Codex focus; heavy Node+daemon+agent stack. |
| [muhwagwa0112/cascadeur-complete](https://github.com/muhwagwa0112/cascadeur-complete) | MCP stdio + LocalAppData queue + hidden Win32 message-window/timer **UI-thread pump**, falling back to UI Automation `Process Pending` | In-app Python command package (bundled Python 3.12); installer updates `Python.Path`/commands; pump claims requests without foregrounding Cascadeur | Tool count **UNVERIFIED**; documented: mocap cleanup (`motion_cleanup_analyze`/`prepare`, `mesh_sample`, `change_commit`), hand/wrist styling, `cascadeur_status`, guarded writes; arbitrary dev Python disabled | **Cascadeur 2026.1.3.0.15619** (exact baseline), Windows | 1★, 5 open issues; created 2026-08-20, pushed **2026-10-16** | **Pre-native architecture** (2026.1.3 has no native server). Mocap-cleanup workflow is a real niche; its README names cascadeur-mcp as neither modified nor required. |
| [ysk424/cascadeur-mcp](https://github.com/ysk424/cascadeur-mcp) | MCP stdio (FastMCP) + **per-call app launch**: localhost TCP server + `cascadeur.exe --run-script commands.externals.csc_mcp_exec` | Installs `csc_mcp_exec.py` under `.../commands/externals/`; callback runs on main thread, then the app exits | **5 tools**: `execute_cascadeur_code`, `get_scene_info`, `capture_viewport`, `export_fbx`, `import_fbx` | Cascadeur **2026** (`FbxSceneLoader` verified) | 0★, 2 forks; created+pushed **2026-06-16**; **no license** | **Superseded.** Per-call launch latency, tiny surface, no license; its own roadmap deferred AutoPhysics/AutoPosing as R&D. |
| [BYGGOLDENSTONE/cascadeur-mcp-bridge](https://github.com/BYGGOLDENSTONE/cascadeur-mcp-bridge) | **Not MCP** — JSON file command/response driver (`io/casc_cmd.json` ↔ `io/casc_resp.json`) | Menu command `Commands → MCP → Start Bridge` runs a foreground polling loop on main thread (UI freezes); `py` op = arbitrary `csc` code | **8 ops**: `ping`, `info`, `get_frame`, `set_frame`, `add_camera`, `fix_preset`, `py`, `stop` | **Cascadeur 2026.1.2**, Windows | 0★; created+pushed **2026-06-26** | **Obsolete.** Native `/run` provides main-thread code execution without the freeze; no MCP layer. |
| [Late-bloomer420/cascadeur-mcp](https://github.com/Late-bloomer420/cascadeur-mcp) | Unknown | Unknown | None documented | Unknown | 0★; created+pushed **2026-09-14**; no license | **Stub.** One-line README; no implementation evidence. Ignore. |
| (excluded) [alphaparkinc/genpark-…-animator-skill](https://github.com/alphaparkinc/genpark-physics-guided-generative-3d-character-animator-skill) | — | — | Agent skill imitating Cascadeur-style physics animating | — | 8★, 2026-08-27 | Not a Cascadeur MCP server; keyword-search noise. |

## (b) Per-implementation notes

### 1. Cascadeur 2026.2 built-in script server (vendor) — the substrate

- Announced with 2026.2 (AWN 2026-08-12; official release notes; render.ru; LinkedIn):
  "opens itself to outside AI agents through a built-in MCP server"; notes say *"Added
  support for a simple MCP server. Available in the Scripts menu through the MCP
  section."*
- Local ground truth (2026.2.3, server v0.3.1): `ThreadingHTTPServer` on
  `127.0.0.1:8765`; `GET /health`; `POST /run {"code": "..."}`; `POST /mcp` handling
  `initialize`, `notifications/initialized`, `tools/list`, `tools/call`,
  `resources/list`, `resources/read`. Protocol version string **"2024-11-05"**.
- **One tool:** `run_script({"code": str})` — queued and executed on the next
  `scene_idle` (`scene_idle_manager.subscribe`), with `csc`, `scene`,
  `csc.app.get_application()` in scope. Tries `compile(..., "eval")`, then `"exec"`;
  returns `{ok, value (repr), error (traceback), messages[]}`.
- **Two resources:** `cascadeur://docs/python-api` (just the API website URL) and
  `cascadeur://modules` (`dir()` of `csc`/`pycsc`).
- Hard-coded **30 s** wait for the idle event; timed-out queued scripts are cancelled.
  No session/auth/token, no SSE/GET stream, no progress/cancellation, no concurrency
  (single queue; calls serialize), and no per-tool descriptions beyond `run_script`'s
  schema. It is a hand-rolled JSON-RPC subset, not the spec's HTTP+SSE or Streamable
  HTTP transport — hence every serious wrapper feeds clients over stdio instead
  (Karylcode's proxy exists for exactly this).
- Menu commands: `MCP.Start script server` / `MCP.Stop script server`; script reload
  stops and restarts the server. Its README warns that `scene.modify*` callbacks can
  throw while `/run` still reports `ok: true` — always check the returned boolean and
  inspect `%LOCALAPPDATA%\Nekki Limited\Cascadeur\logs\cascadeur_log.log` (doc drift:
  the README mentions a `stdout` field that the v0.3.1 source does not return; source
  returns `messages`).
- **Can:** anything Python can do in Cascadeur, on the main thread, at a safe point.
  **Cannot:** provide typed/guardrailed tools, authenticate callers, run >30 s
  operations, or connect to typical MCP clients that expect stdio/Streamable HTTP.
  Those gaps are the entire market for the projects below.

### 2. cascadeur-mcp (figgiee/poppet) — our project

- Public repo: MIT, 0★/0 forks, created 2026-05-24, last push **2026-05-25**, 176 KB,
  Python. The public snapshot predates 2026.2 by ~3 months.
- Current design (local README + `docs/architecture.md`): MCP stdio FastMCP host process
  + **43 tools + 1 resource**; Cascadeur-side package in `user_scripts/`; file queue in
  `%LOCALAPPDATA%\cascadeur-mcp\`; auto-drain via `scene_activated`/`scene_opened` event
  hooks plus best-effort `SetForegroundWindow` nudge; `Commands → cascadeur-mcp → Process
  Pending` fallback. Target **Cascadeur 2025.3.3**.
- The 2025.3.3 constraints in `docs/architecture.md` (no PySide, no `csc` main-thread
  scheduler, starved background threads) **no longer hold on 2026.2**: release notes/AWN
  add PySide/QML UI scripting, and the native server itself runs a Python HTTP server +
  `scene_idle` subscription inside Cascadeur. cascadeur-mcp's own doc predicted the pivot
  condition: *"If a future Cascadeur version ships PySide or exposes a main-thread
  scheduler, the socket design becomes viable."* That version has shipped.
- cascadeur-mcp's moat is the tool table: verified `csc` semantics for telemetry,
  AutoPosing/AutoPhysics convergence polling, FBX export (`FbxSceneLoader`), layer and
  keyframe ops, selection via `scene.modify_with_session`, plus documented quirks
  (Joint vs `_Box` controller, no public Vec3/Quaternion constructors, `ScriptsDir`
  hard-replacement crash, `call_action` fire-and-forget).

### 3. gprethesh/cascadeur-mcp

- 36 named tools + optional 37th scripting tool (`cascadeur_run_script`, gated by
  `--allow-scripts`). Broadest third-party coverage claim: projects/scene tabs, rig/
  object search, body + all-15-finger pose batches, keys/interpolation, track/frame
  selection, motion sampling, camera framing, **PNG review returned as MCP image
  content**, FBX import/export, curated action catalog (physics/AutoPosing/retargeting/
  cycles), live signature discovery.
- Transport: stdio MCP host writes into a local mailbox; a generated `start_bridge.py`
  (run once per Cascadeur launch from `Window → Python Console`) installs a Qt-timer
  bridge on the main thread. Requires `csc`, **PySide6**, event-message manager. README:
  *"Do not start Cascadeur's built-in MCP server for this integration"*; *"It does not
  use Cascadeur's built-in MCP server, patch the app, or install Python packages into the
  app's embedded Python."*
- Tested on an Apple-silicon macOS install (embedded Python 3.11), build reporting
  `inHouse`/API `dev`; Windows/Linux unverified. Honest limits: physics/menu actions are
  "dispatched, not verified"; native Python video export crashed the tested build.
- Verdict: strongest direct competitor on breadth and review loop, but the per-launch
  console bootstrap and native-server rejection make it strictly more setup-heavy than
  a native-server-based design.

### 4. MnxD2A6/cascadeur-mcp

- Alpha `0.5.0a13`, targets **Cascadeur 2026.2.2** on Windows with Python 3.12; README
  validates only the developer's machine. Not on PyPI; matching source/wheel from the
  a13 prerelease.
- Transport: MCP stdio (official MCP Python SDK v1) → **private local JSON queue**
  (owner+SYSTEM ACLs) → in-app bridge started by a **host hook** installed with
  `python -m cascadeur_mcp.manage install-host --cascadeur-home … --apply` (generates a
  startup hook; `HOOK_CONFLICT` instead of overwrite; `uninstall-host --apply` for
  exact-match removal). `doctor --live` reads the loaded host contract.
- Engineering posture worth copying: fixed allowlist, no arbitrary shell/Python/menu
  tool; bilateral **write-contract revision 3** checks between host and client; bounded
  payloads; 121-frame clip limit; ≤8-frame ordinary pose sequences (opt-in 64-pose
  sampled motion); structured errors; explicit "timeout = unknown outcome, read back,
  never auto-retry"; session snapshots + rollback + persistent recovery quarantine;
  license-entitlement check before FBX export.
- Known risks it documents itself: native shutdown instability (`0xC0000005` in
  `Qt6Core.dll`, also reproduced without MCP), no cross-machine validation.

### 5. Karylcode/cascadeur-mcp-plus

- Newest project (2026-10-23..25, v0.6.0), explicitly built for **Cascadeur 2026.2 with
  the built-in script server (tested 2026.2.3)**; Windows 10/11; MIT; Python 3.11+ proxy
  with **zero pip dependencies**.
- Architecture to study: `MCP client —stdio→ proxy.py —HTTP→ in-app server
  (127.0.0.1:48766)`. If the in-app server is down, the proxy boots it by posting
  `start_mcp_plus.py` to the **native 8765 `/run`** endpoint (waits ≤10 s, retries once).
  The proxy answers `initialize`/`ping` itself while Cascadeur is closed and serves a
  cached `tools/list` from `tools_manifest.json`; `/health` checks guard both ports;
  `doctor` covers install, ports **8765/48766**, servers and registered clients; `setup`
  registers Claude Code/Codex/Cursor/VS Code; `autostart enable` (one UAC prompt) makes
  Cascadeur start both servers itself.
- In-app server: bundled PySide6 shares Cascadeur's Qt runtime → GUI-thread dispatch via
  QTimer every 25 ms, re-entrant jobs (a modal dialog doesn't block the job that closes
  it), scene-idle tools for rig mode/imports, background jobs with `job_id` +
  `jobs.get` polling, per-tool `requires` compatibility list checked at startup.
  Unavailable tools stay visible prefixed "Unavailable in this Cascadeur version:" and
  return the missing capability instead of half-failing (`status.status` re-checks).
- 27 tools: 23 grouped-action tools + `run_python`, `batch`, `screenshot`,
  `video_mocap`. Coverage: scenes/FBX/GLB, characters/rigs/Quick Rig/retarget,
  poses/AutoPosing/mirror, keys/cycles/interpolation/IK-FK, animation layers,
  AutoPhysics/cleanup/AI inbetweening+motion generation/video mocap, renders
  (image/sequence/MP4/contact sheet), camera/display, full UI automation
  (`ui_input.click/drag/type`, `ui_inspect.tree/dialogs`, QtTest-synthesized input,
  Win32 `PrintWindow` screenshots — `QQuickWindow.grabWindow` crashed the app),
  run_python/batch/jobs/history/actions/log.
- Verdict: clearest proof that "native server + typed layer" is a viable product
  direction. Weak spots: Windows-only, a second in-app HTTP server to maintain, and GUI
  automation for the long tail.

### 6. BrianFinch-1/cascadeur-codex-bridge

- "Local, capability-detected integration between Codex and Cascadeur **2026.2 or
  newer**", Windows 10/11; MIT; 2★. Unusually productized distribution for this niche:
  checked-in Windows ZIPs (2026-10-18 "p19 safety rebuild"), SHA256SUMS, build manifest,
  install/diagnostic scripts, English/Chinese READMEs.
- Stack: dependency-free Node.js 18+ stdio MCP server + Python 3.11 agent executed on
  Cascadeur's main thread + authenticated Python bridge daemon (plus a mock runtime for
  tests). Security profiles `readonly`/`standard`; **no arbitrary Python execution**;
  writes require revision guards plus explicit dry-run/commit; capability matrix instead
  of assumed support.
- Documented tool groups: scene inspection, MMD character analysis (VMD dry-run),
  Outline hierarchy editing, viewport capture, guarded scene changes, diagnostics. Exact
  tool count UNVERIFIED.
- Verdict: niche (MMD/Codex) but sets the packaging/safety bar; its Node+daemon+agent
  stack is heavier than needed once the native server exists.

### 7. muhwagwa0112/cascadeur-complete

- Aimed at exact baseline **Cascadeur 2026.1.3.0.15619** (pre-native-MCP) on Windows;
  MIT; 1★, 5 open issues; repo/package name `cascadeur-complete`.
- Host: stdio MCP server + Python 3.11-compatible command package inside Cascadeur that
  drains the LocalAppData request queue on the UI thread. A hidden **message-only Win32
  window with a timer** acts as a UI-thread pump so Cascadeur is never foregrounded and
  nothing is clicked; if the pump is stale/disabled or another scene tab/modal blocks
  it, the host falls back to UI Automation `Process Pending`. The bridge yields to
  Cascadeur's event loop around rendering/dialogs/scene loads.
- Differentiator: a real **mocap-cleanup workflow** — `motion_cleanup_analyze` (per-frame
  foot-skate/slides/drags/finger spikes), `motion_cleanup_prepare` (one protected
  whole-clip write: quadratic-program foot-contact solve, finger soft-limits/fan, arm
  clearance on the skinned mesh, wrist/hand styling), `mesh_sample`, `change_commit`.
  README reports mean foot skating 0.98 → 0.34 cm/frame on a 986-frame clip.
- Installer path: signed Inno Setup installer + SBOM + provenance claims (README claim;
  UNVERIFIED), no Python/uv/cascadeur-mcp required, and explicitly *"cascadeur-mcp is neither modified
  nor required"* — evidence that cascadeur-mcp is the project this author benchmarked against.
- Verdict: architecturally pre-native (its whole UI pump solves what native `scene_idle`
  now solves), but the mocap-cleanup workflow is genuinely differentiated.

### 8. ysk424/cascadeur-mcp

- 5 tools (`execute_cascadeur_code`, `get_scene_info`, `capture_viewport`, `export_fbx`,
  `import_fbx`); FastMCP stdio; **per-call** `cascadeur.exe --run-script
  commands.externals.csc_mcp_exec` with a localhost TCP callback (default port 53151), so
  every call pays app-launch latency. Installer copies one command file under
  `.../commands/externals/`. No license file.
- Its README documents the verified `FbxSceneLoader` method list for Cascadeur 2026
  (`export_all_objects`, `export_joints`, `export_joints_selected`, `export_model`,
  `export_scene_selected`, `add_model`, `import_animation`, `import_model`,
  `import_scene`), and explicitly defers AutoPhysics/AutoPosing as "an R&D task rather
  than a thin wrapper" — independent confirmation of how hard those commands are.
- Verdict: superseded by native `run_script` + a real bridge; historically interesting.

### 9. BYGGOLDENSTONE/cascadeur-mcp-bridge

- Not an MCP server despite the name: JSON file-driver + a `Commands → MCP → Start
  Bridge` menu command that polls `io/casc_cmd.json` on the main thread and writes
  `io/casc_resp.json`. Ops: `ping`, `info`, `get_frame`, `set_frame`, `add_camera`,
  `fix_preset` (controller-fixation presets), `py` (arbitrary `csc` code), `stop`.
- Tested Cascadeur 2026.1.2 Windows. Explicitly chosen to dodge AV heuristics
  (`Trojan:Win32/ClickFix` flagged a PowerShell TcpClient one-liner) and because
  background threads are starved. Cascadeur's **UI freezes** while the loop runs
  (auto-closes after 240 s or on `stop`).
- Verdict: obsolete. Native `POST /run` does the same main-thread execution without the
  freeze and with a proper protocol surface.

### Press / community coverage of the 2026.2 native server

- [AWN, 2026-08-12](https://www.awn.com/news/cascadeur-ships-20262-animation-layers-and-3-new-languages):
  "opens itself to outside AI agents through a built-in MCP server"; PySide/QML UI,
  Python stubs, BVH import.
- [Official 2026.2 notes](https://cascadeur.com/help/category/319): "Added support for a
  simple MCP server. Available in the Scripts menu"; PySide UI elements; Commands/Scripts
  split.
- [render.ru, 2026-08-06](https://render.ru/ru/news/post/28365): MCP lets LLM tools (e.g.
  Claude) drive Cascadeur; text/voice control framed as the goal.
- [LinkedIn — Jim Thacker](https://www.linkedin.com/posts/jimthacker_nekki-just-released-cascadeur-20262-its-activity-7491146116336488449-fxNm):
  "'simple' MCP server for connecting Cascadeur to external AI tools"; PySide support.
  [LinkedIn — Tom Borovskis](https://www.linkedin.com/posts/tom-borovskis-04a7851a_animation-layers-cascadeur-20262-feature-activity-7492906835272830977-Ogf5):
  additive layers alpha, easing, +Chinese/Japanese/Korean.
- No Reddit/YouTube/Discord coverage found (UNVERIFIED — absence of search hits only).

## (c) What cascadeur-mcp should keep / drop / steal

The 2026.2 native server solves "run code on the main thread at a safe point". The
remaining product problems are (1) a compliant, ergonomic MCP front end, (2) typed/
verified tools instead of raw Python, (3) safety and long-operation semantics, (4)
review/output workflows, (5) distribution and diagnostics. cascadeur-mcp already owns (2) at a
depth no competitor matches; it currently owns nothing in (1)/(3)/(4)/(5) on 2026.2.

### Keep

1. **The verified tool catalog and `csc` domain knowledge.** 43 tools with real
   semantics (AutoPhysics convergence polling, verified `FbxSceneLoader` export,
   telemetry range reads, layer/keyframe patterns from bundled scripts, selection via
   `modify_with_session`) remains the deepest verified inventory in the field; no
   36/27/37-tool competitor claims cascade-level verification.
2. **MCP stdio as the client-facing transport.** Native `/mcp` is a JSON-RPC subset
   without SSE/sessions, so clients need a stdio shim; Karylcode proves the proxy pattern
   works offline (answers `initialize`/`ping`, caches the tool list).
3. **`execute_csc_code` escape hatch + live schema resource** (`csc://schema`), kept
   **opt-in/gated** (gprethesh's `--allow-scripts` model) and paired with a guide.
4. **Multi-signature dispatcher fallbacks and structured responses.** The `csc` API
   drifted to 2026.2 (Commands menu split, etc.); reporting which call shape worked is a
   real API-drift defense.
5. **MIT license + `uvx`/pip host-process install.** A zero-Cascadeur-install footprint
   is now achievable and differentiates from every repo that asks users to edit
   `settings.json`, paste a console script, or install a signed setup.

### Drop

1. **The file queue as primary transport — and with it the Cascadeur-side install,
   `Process Pending` menu, and `SetForegroundWindow` nudge.** Native `/mcp` and `/run`
   execute on `scene_idle`; no user_scripts copy, no menu click, no focus edge, no
   25–500 ms file-I/O floor. Keep the file queue only as a legacy fallback for 2025.3.x.
2. **The 2025.3.3 assumptions in `docs/architecture.md`** (no PySide, no main-thread
   scheduler, starved threads). 2026.2 added PySide/QML scripting, and the native server
   runs a Python HTTP server + `scene_idle` subscription inside Cascadeur. The stated
   pivot condition is met; update the doc.
3. **"43 flat tools" as a selling point.** glama's tool-choice analysis of a 37-tool
   server scored disambiguation 2/5 and tool count 2/5, citing overlapping
   `get_transform`/`get_local_transform`/`get_global_transform`/`get_pose`/… variants.
   "43 ungrouped tools" is now a liability — see steal #1 for the proven fix.
4. **Any remote/multi-machine or public HTTP-server ambition.** Native server is
   loopback-bound and unauthenticated; cascadeur-mcp should stay a local stdio server talking to
   `127.0.0.1:8765`.

### Steal

1. **From Karylcode — proxy shape and operational polish.** stdio proxy answers
   `initialize`/`ping` with Cascadeur closed, caches `tools/list`, checks `/health`,
   retries once after app restart, runs requests on threads so slow calls don't block
   pings, per-tool `requires` capability checks with "Unavailable in this Cascadeur
   version:" descriptions, `doctor` covering ports + registered clients, one-command
   `setup`, optional autostart. Adopt all of it except the second in-app HTTP server.
2. **From MnxD2A6 — the safety contract.** Capability handshake
   (`get_bridge_capabilities`), a write-contract revision echo between cascadeur-mcp and its
   Cascadeur-side dispatcher, "timeout = unknown outcome → read back, never auto-retry",
   snapshot/rollback/recovery-status, preflight readiness reads, bounded payloads/frame
   ranges, structured errors, no arbitrary code by default.
3. **From gprethesh — agent-facing review UX.** Serve a `cascadeur://guide` resource
   (workflows, verified-vs-dispatched, API traps), return viewport renders as MCP image
   content so the model can visually verify, gate scripting behind `--allow-scripts`,
   sandbox normal tool paths to a workspace, and label menu-action tools "dispatch, not
   completion".
4. **From muhwagwa — a workflow differentiator.** Their mocap-cleanup suite (foot-skate
   QP, finger cleanup, arm clearance, contact sheets) is a packaged workflow, not
   another primitive. cascadeur-mcp should ship one or two similarly opinionated workflows
   (e.g. block poses → AutoPose → verify via telemetry → contact sheet); that is harder
   to commoditize than raw tool count.
5. **From the native server — idle semantics and the modify-return trap.** Subscribe to
   the same `scene_idle` event (or accept that `run_script` runs at idle); check every
   `scene.modify*` boolean return — exceptions can be logged while the RPC still reports
   success — and read the tail of `%LOCALAPPDATA%\Nekki Limited\Cascadeur\logs\cascadeur_log.log`
   on failure.
6. **Don't copy Karylcode's "bootstrap a second server" step.** cascadeur-mcp's dispatchers are
   already pure Python functions; the simplest 2026.2 design is one bootstrap
   `run_script` that loads the dispatcher bundle (embedded source or a temp-dir module),
   then compact calls like `cascadeur-mcp.dispatch({"op": "set_controller_position",
   "params": {...}})`. No user_scripts install, no menu command, no second HTTP port, no
   per-launch console paste.

### Top 5 concrete recommendations after the comparison

1. **Re-architect the transport now: stdio MCP → native `8765` HTTP.** Detect
   `/health`; bootstrap the dispatcher bundle once via `run_script`; send compact JSON
   ops through `run_script`; keep the file queue only behind a legacy flag for 2025.3.x.
   Delete `settings.json` edits and the `Process Pending`/nudge machinery from the
   primary path.
2. **Re-shape the tool surface to the Karylcode grouping pattern (~15–20 tools with an
   `action` parameter)** while keeping every verified operation, and add MCP annotations
   (`readOnlyHint`/`destructiveHint`/`idempotentHint`). Ship a `cascadeur://guide`
   resource plus a generated tool manifest; keep `execute_csc_code` opt-in.
3. **Implement long-operation semantics instead of one blocking call.** The native call
   is hard-capped at 30 s, so AutoPhysics/AutoPosing/export/render become start/poll jobs
   (`job_id` + bounded `run_script` polls, progress text) under the "timeout = unknown
   outcome, read back first" contract. This also handles `call_action`'s
   fire-and-forget behavior.
4. **Add the safety layer the native server lacks:** version/capability handshake on
   first call (Cascadeur version, dispatcher protocol revision, available op set),
   preflight readiness for edits, modify-return-value checks with log-tail tracebacks,
   snapshot/undo guidance, bounded payloads, and a clear local trust-boundary statement
   (native `8765` is unauthenticated on loopback; cascadeur-mcp must not widen that).
5. **Ship distribution + diagnostics:** `cascadeur-mcp doctor` (native `/health` + version +
   port-in-use + dispatcher load test), one-command client registration for Claude Code /
   Claude Desktop / Codex / Cursor, README matrix "2026.2.3 primary; 2025.3.x legacy via
   file queue", and a recorded 2026.2.3 end-to-end demo replacing the 2025.3.3
   Process-Pending demo. Cheapest way to look more mature than MnxD2A6's alpha and more
   current than gprethesh's manual bridge.

## (d) Sources

Repos (metadata via `api.github.com/repos/...`; READMEs via
`raw.githubusercontent.com/<owner>/<repo>/main/README.md` unless noted):

- https://github.com/figgiee/poppet — repo metadata; README; local `README.md`,
  `docs/architecture.md` (2025.3.3 constraints, pivot condition).
- https://github.com/gprethesh/cascadeur-mcp — README (36+1 tools, mailbox/Qt-timer
  bridge, no native server, macOS test, limits); https://glama.ai/mcp/servers/gprethesh/cascadeur-mcp
- https://github.com/MnxD2A6/cascadeur-mcp — README (alpha 0.5.0a13, 2026.2.2, host hook,
  safety contract); glama.ai `.../MnxD2A6/cascadeur-mcp` and `.../schema` (37 tools).
- https://github.com/Karylcode/cascadeur-mcp-plus — README (27 tools, 2026.2.3, ports/
  autostart/doctor); `docs/how-it-works.md` (native `/run` bootstrap, 48766, QTimer).
- https://github.com/BrianFinch-1/cascadeur-codex-bridge — README (2026.2+, Node stdio +
  Python agent + daemon, profiles, MMD/Outline/viewport, packages); `docs/` listing.
- https://github.com/muhwagwa0112/cascadeur-complete — README (2026.1.3.0.15619, UI pump
  + UI Automation fallback, mocap cleanup, "cascadeur-mcp is neither modified nor required").
- https://github.com/ysk424/cascadeur-mcp — README (per-call `--run-script`, 5 tools,
  TCP 53151, FbxSceneLoader list, roadmap).
- https://github.com/BYGGOLDENSTONE/cascadeur-mcp-bridge — README (file bridge, menu
  command, ops, 2026.1.2, UI freeze, AV rationale).
- https://github.com/Late-bloomer420/cascadeur-mcp — README (stub).
- GitHub REST searches: `api.github.com/search/repositories?q=cascadeur-mcp`,
  `?q=cascadeur+mcp`, `?q=cascadeur+run_script` (0 results),
  https://github.com/topics/cascadeur.

Vendor / native server / press:

- Local install 2026.2.3:
  `C:\Users\sandv\AppData\Local\Cascadeur\resources\scripts\python\scripts\mcp\script_server\server.py`
  (297 lines; port 8765, protocol `2024-11-05`, single `run_script` queue, 30 s wait,
  two resources) and `...\mcp\script_server\README.md`, `...\mcp\start_server.py`.
- https://cascadeur.com/help/category/319 — official 2026.2 release notes ("simple MCP
  server", PySide UI scripting, Commands/Scripts split, BVH import, additive layers,
  easing, localizations).
- https://www.awn.com/news/cascadeur-ships-20262-animation-layers-and-3-new-languages —
  AWN, published 2026-08-12, built-in MCP server + PySide/QML + release context.
- https://render.ru/ru/news/post/28365 — release coverage (MCP control via LLMs).
- https://www.linkedin.com/posts/jimthacker_nekki-just-released-cascadeur-20262-its-activity-7491146116336488449-fxNm
  — "'simple' MCP server"; PySide support (Nekki/CG Channel repost).
- https://www.linkedin.com/posts/tom-borovskis-04a7851a_animation-layers-cascadeur-20262-feature-activity-7492906835272830977-Ogf5
  — 2026.2 feature post (additive layers, 3 languages), 2026-08-10.

Marked **UNVERIFIED** in this document: gprethesh's exact Cascadeur build/version
(README says `inHouse`/API `dev`, PySide6 required); BrianFinch exact tool count;
muhwagwa exact tool count and signed-installer/SBOM claims; "no Reddit/YouTube/Discord
coverage" (absence of search hits only); whether any private/unlisted wrapper of native
`8765` exists.
