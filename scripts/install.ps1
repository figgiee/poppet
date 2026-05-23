#requires -Version 5.1
<#
.SYNOPSIS
    Install Poppet into Cascadeur 2025.3.x.

.DESCRIPTION
    Default mode: additive Python.Path + Python.Commands override (no admin needed).
      - Copies cascadeur_side/poppet/ to %LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts\poppet\
      - Adds user_scripts to settings.json Python.Path
      - Appends "poppet" to settings.json Python.Commands list
      - Backs up settings.json to settings.json.bak first
      - Leaves ScriptsDir alone (replacing it would FATAL Cascadeur — the
        "parts" rig data only exists inside the bundled scripts dir).

    Admin mode (-Elevate): writes directly into the bundled commands dir.
      - Requires running PowerShell as Administrator.
      - Does NOT modify settings.json.

.PARAMETER Elevate
    Install into Program Files. Requires admin.
#>

param(
    [switch]$Elevate = $false
)

$ErrorActionPreference = "Stop"

$cfgDir = Join-Path $env:LOCALAPPDATA "Nekki Limited\Cascadeur"
$settingsPath = Join-Path $cfgDir "settings.json"
$repoRoot = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $repoRoot "cascadeur_side\poppet"

if (-not (Test-Path $srcDir)) { throw "Source not found: $srcDir" }

function Find-BundledCommandsDir {
    $candidates = @(
        "C:\Program Files\Cascadeur\resources\scripts\python\commands",
        "C:\Program Files\Nekki\Cascadeur\resources\scripts\python\commands",
        "C:\Cascadeur\resources\scripts\python\commands"
    )
    foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
    throw "Could not locate Cascadeur install."
}

function Copy-PoppetTree($from, $to) {
    if (Test-Path $to) {
        Write-Host "Removing existing install at $to"
        Remove-Item -Path $to -Recurse -Force
    }
    Write-Host "Copying $from -> $to"
    Copy-Item -Path $from -Destination $to -Recurse
    # Prune any pycache that snuck in.
    Get-ChildItem -Path $to -Recurse -Force -Directory -Filter "__pycache__" |
        ForEach-Object { Remove-Item -Path $_.FullName -Recurse -Force }
}

if ($Elevate) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
    if (-not $isAdmin) { throw "-Elevate requires running PowerShell as Administrator." }

    $dstDir = Join-Path (Find-BundledCommandsDir) "poppet"
    Write-Host "Admin mode - target: $dstDir"
    Copy-PoppetTree $srcDir $dstDir
    Write-Host ""
    Write-Host "[OK] Admin install complete. No settings.json change required."
}
else {
    if (-not (Test-Path $settingsPath)) {
        throw "Cascadeur settings.json not found at $settingsPath. Launch Cascadeur once first."
    }

    $userScripts = Join-Path $cfgDir "user_scripts"

    # Clean any leftover from the older (broken) ScriptsDir-override layout.
    $oldLayout = Join-Path $userScripts "commands"
    if (Test-Path $oldLayout) {
        Write-Host "Removing prior layout: $oldLayout"
        Remove-Item -Path $oldLayout -Recurse -Force
    }

    if (-not (Test-Path $userScripts)) {
        New-Item -ItemType Directory -Path $userScripts -Force | Out-Null
    }

    $dstDir = Join-Path $userScripts "poppet"
    Copy-PoppetTree $srcDir $dstDir

    # Update settings.json additively.
    $backupPath = "$settingsPath.bak"
    if (-not (Test-Path $backupPath)) {
        Copy-Item -Path $settingsPath -Destination $backupPath
        Write-Host "Backed up settings.json -> $backupPath"
    }

    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json

    # NEVER set ScriptsDir to a custom path - it replaces (doesn't extend)
    # the bundled scripts dir and FATAL-crashes Cascadeur because rig "parts"
    # are lost. If a prior run set it, reset to empty.
    if ($settings.ScriptsDir -ne "") {
        Write-Host "Resetting ScriptsDir to empty (additive mode)"
        $settings.ScriptsDir = ""
    }

    # Ensure Python.Path includes user_scripts.
    $pathList = New-Object System.Collections.ArrayList
    if ($settings.Python.Path) { foreach ($p in $settings.Python.Path) { [void]$pathList.Add($p) } }
    if ($pathList -notcontains $userScripts) {
        [void]$pathList.Add($userScripts)
        Write-Host "Added to Python.Path: $userScripts"
    }
    $settings.Python.Path = @($pathList)

    # Ensure Python.Commands includes 'poppet'.
    $cmdList = New-Object System.Collections.ArrayList
    if ($settings.Python.Commands) { foreach ($c in $settings.Python.Commands) { [void]$cmdList.Add($c) } }
    if ($cmdList -notcontains "poppet") {
        [void]$cmdList.Add("poppet")
        Write-Host "Appended to Python.Commands: poppet"
    }
    $settings.Python.Commands = @($cmdList)

    $fi = Get-Item $settingsPath -Force
    if ($fi.IsReadOnly) { $fi.IsReadOnly = $false }
    $json = $settings | ConvertTo-Json -Depth 10
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($settingsPath, $json, $utf8NoBom)

    Write-Host ""
    Write-Host "[OK] Additive install complete."
    Write-Host "     Target: $dstDir"
    Write-Host "     settings.json: ScriptsDir untouched, Python.Path + Python.Commands extended."
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart Cascadeur."
Write-Host "  2. Open Commands menu - should see Poppet entries."
Write-Host "  3. Verify Qt integration: Commands -> Poppet -> POC Tick Loop"
Write-Host "  4. Start the real server: Commands -> Poppet -> Start Server"
Write-Host "  5. From a terminal: python .\scripts\poc_client.py"
