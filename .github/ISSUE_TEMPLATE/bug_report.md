---
name: Bug report
about: Report a bug in Poppet (Cascadeur MCP)
labels: bug
---

## What happened

<!-- One or two sentences describing the problem. -->

## Reproduce

1. <!-- Step 1 (e.g., "Started Cascadeur 2025.3.3 with Cascy.casc loaded") -->
2. <!-- Step 2 (e.g., "Asked Claude: 'set pelvis to (0,0,30) at frame 0'") -->
3. <!-- What Poppet tool/command was actually invoked, ideally the JSON request -->

## Expected

<!-- What should have happened. -->

## Actual

<!-- What actually happened — paste error messages or response JSON verbatim. -->

## Environment

- Cascadeur version: <!-- e.g., 2025.3.3 -->
- Poppet version: <!-- run: pip show poppet-mcp | grep Version -->
- OS: <!-- e.g., Windows 11 Pro 23H2 -->
- Python: <!-- output of `python --version` in the MCP server env -->
- MCP client: <!-- Claude Code / Claude Desktop / Cursor / other -->

## install_check.py output

```text
<!-- Paste output of: python scripts/install_check.py -->
```

## Dispatcher log

```text
<!-- Last ~20 lines of %LOCALAPPDATA%\poppet-mcp\dispatcher.log -->
```
