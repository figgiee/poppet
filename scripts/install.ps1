#requires -Version 5.1
<#
.SYNOPSIS
    Install the Poppet Cascadeur-side command script.

.DESCRIPTION
    Copies cascadeur_side/poppet/ into Cascadeur's commands folder.
    Auto-detects the commands folder from settings.ini, with fallback probes
    of known install paths.

.PARAMETER CommandsDir
    Override the auto-detected commands folder.
#>

param(
    [string]$CommandsDir = ""
)

$ErrorActionPreference = "Stop"

function Find-CascadeurCommandsDir {
    # 1. Read ScriptsDir from settings.ini.
    $iniPath = Join-Path $env:LOCALAPPDATA "Nekki Limited\Cascadeur\settings.ini"
    if (Test-Path $iniPath) {
        $content = Get-Content $iniPath -Raw
        if ($content -match '(?m)^\s*ScriptsDir\s*=\s*(.+?)\s*$') {
            $custom = $Matches[1].Trim()
            if ($custom -and (Test-Path $custom)) {
                Write-Host "Using ScriptsDir from settings.ini: $custom"
                return $custom
            }
        }
    }

    # 2. Probe known install paths.
    $candidates = @(
        "C:\Program Files\Nekki\Cascadeur 2025.3\resources\scripts\python\commands",
        "C:\Program Files\Cascadeur 2025.3\resources\scripts\python\commands",
        "C:\Cascadeur 2025.3\resources\scripts\python\commands",
        "C:\Program Files\Nekki\Cascadeur\resources\scripts\python\commands",
        "C:\Cascadeur\resources\scripts\python\commands"
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) {
            Write-Host "Detected commands folder: $p"
            return $p
        }
    }
    throw "Could not locate Cascadeur commands folder. Set ScriptsDir in $iniPath or re-run with -CommandsDir <path>."
}

if (-not $CommandsDir) {
    $CommandsDir = Find-CascadeurCommandsDir
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $repoRoot "cascadeur_side\poppet"
$dstDir = Join-Path $CommandsDir "poppet"

if (-not (Test-Path $srcDir)) {
    throw "Source not found: $srcDir"
}

if (Test-Path $dstDir) {
    Write-Host "Removing existing install at $dstDir"
    Remove-Item -Path $dstDir -Recurse -Force
}

Write-Host "Copying $srcDir -> $dstDir"
Copy-Item -Path $srcDir -Destination $dstDir -Recurse

Write-Host ""
Write-Host "[OK] Cascadeur-side install complete."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart Cascadeur."
Write-Host "  2. Verify QTimer compat: Commands -> Poppet -> POC Tick Loop"
Write-Host "     (viewport should stay responsive; re-run to stop)"
Write-Host "  3. Start the real server: Commands -> Poppet -> Start Server"
Write-Host "  4. (Once) Refresh the introspection schema: Commands -> Poppet -> Refresh Schema"
Write-Host "  5. Wire up your MCP client:"
Write-Host ""
Write-Host "     claude_desktop_config.json:"
Write-Host '     {'
Write-Host '       "mcpServers": {'
Write-Host '         "poppet": { "command": "uvx", "args": ["poppet-mcp"] }'
Write-Host '       }'
Write-Host '     }'
Write-Host ""
Write-Host "     Or Claude Code:"
Write-Host "     claude mcp add poppet -- uvx poppet-mcp"
