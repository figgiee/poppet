# Poppet research notes

Background research that informed Poppet 1.0. Both documents are **snapshots**
(2026-10-26) and are kept for provenance, not as current documentation — the code
and the user docs win if they disagree.

| Doc | Scope | Method |
|---|---|---|
| [github-landscape.md](github-landscape.md) | Public Cascadeur MCP implementations vs. poppet, including Cascadeur 2026.2's built-in script server | GitHub REST/API + README/design-doc reading; press and release-note coverage |
| [python-api-diff.md](python-api-diff.md) | Cascadeur-side Python API compatibility audit: 2025.3.3 → 2026.2.3 | Static diff of the two installs' `resources/scripts/**`, `.pyi` stubs, bundled scripts, `pycsc` sources; no Cascadeur launched |

## Five takeaways

1. **The 2026.2 script server is the substrate, and it is intentionally minimal.**
   One tool (`run_script`), two resources, plain JSON-RPC over loopback HTTP, ~30 s
   hard cap, no auth, no SSE/sessions. It has no typed tools, safety
   classification, or long-operation semantics — exactly the layer Poppet adds.
2. **Nobody else occupies poppet's niche.** Of the public implementations surveyed,
   only Karylcode's `cascadeur-mcp-plus` builds on the native server (and only to
   bootstrap its own in-app server); the rest ship their own Cascadeur-side bridges
   (`user_scripts` packages, host hooks, PySide servers). Poppet is the only
   install-free, typed layer over the native `run_script` primitive.
3. **The `csc.*` API barely moved between 2025.3.3 and 2026.2.3; the installer
   contract did.** The audit's one true regression is the command/action
   registration change (`command_name()` → `name()`), which removed Poppet 0.x's
   `user_scripts` menu commands. Poppet 1.0 sidesteps Cascadeur-side registration
   entirely by bootstrapping its runtime through `run_script`.
4. **Both installs embed Python 3.11 (not 3.8), and 2026.2 adds `.pyi` stubs.**
   The historic "Python 3.8 compatible" constraint for `cascadeur_side/` was based
   on a wrong premise; 2026.2's stubs make static typing/fixes against the real
   2026.2 surface practical.
5. **The audit flags handler risk, and the user docs carry the markers.** Eight
   handlers need call-shape fixes (e.g. `set_layer_visible`, `delete_object`,
   `screenshot_viewport`, `save_scene`) and two have no 2026.2 equivalent
   (`get_active_layer` / `set_active_layer`). The README's `known risk` labels and
   TROUBLESHOOTING's "Tool-specific known issues" point back to
   [python-api-diff.md](python-api-diff.md).
