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
$eventsSrcDir = Join-Path $repoRoot "cascadeur_side\poppet_events"

if (-not (Test-Path $srcDir)) { throw "Source not found: $srcDir" }
if (-not (Test-Path $eventsSrcDir)) { throw "Events source not found: $eventsSrcDir" }

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

    $commandsDir = Find-BundledCommandsDir
    $eventsDir = Join-Path (Split-Path -Parent $commandsDir) "events"

    $dstDir = Join-Path $commandsDir "poppet"
    Write-Host "Admin mode - commands target: $dstDir"
    Copy-PoppetTree $srcDir $dstDir

    # Events are addressed by subpackage name (scene_activated, etc.), so
    # we merge our event handlers INTO the bundled events/ tree, side-by-side
    # with example.py — no settings.json change needed because 'events' is
    # already in Python.Events by default.
    foreach ($evtName in @("scene_activated", "scene_opened")) {
        $evtSrc = Join-Path $eventsSrcDir "$evtName\poppet_drain.py"
        if (-not (Test-Path $evtSrc)) {
            Write-Host "Skipping $evtName (no handler in source tree)"
            continue
        }
        $evtDst = Join-Path $eventsDir "$evtName\poppet_drain.py"
        $evtDstDir = Split-Path -Parent $evtDst
        if (-not (Test-Path $evtDstDir)) {
            New-Item -ItemType Directory -Path $evtDstDir -Force | Out-Null
        }
        Copy-Item -Path $evtSrc -Destination $evtDst -Force
        Write-Host "Copied event handler: $evtDst"
    }

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

    $dstEventsDir = Join-Path $userScripts "poppet_events"
    Copy-PoppetTree $eventsSrcDir $dstEventsDir

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

    # Ensure Python.Events includes 'poppet_events'. Cascadeur's events_rule.py
    # walks each entry as a Python package; subpackages must be named after the
    # event (scene_activated, etc.) and contain .py modules with a run(scene)
    # function — see C:/Program Files/Cascadeur/resources/scripts/python/events_rule.py.
    $evList = New-Object System.Collections.ArrayList
    if ($settings.Python.PSObject.Properties['Events']) {
        if ($settings.Python.Events) {
            foreach ($e in $settings.Python.Events) { [void]$evList.Add($e) }
        }
    }
    if ($evList -notcontains "poppet_events") {
        [void]$evList.Add("poppet_events")
        Write-Host "Appended to Python.Events: poppet_events"
    }
    # Add the Events key if it didn't exist (older user settings.json
    # don't include it because it defaults to ['events'] in the bundled
    # resources/settings.json — but the user file overrides).
    if (-not $settings.Python.PSObject.Properties['Events']) {
        Add-Member -InputObject $settings.Python -MemberType NoteProperty -Name "Events" -Value @($evList)
    } else {
        $settings.Python.Events = @($evList)
    }

    $fi = Get-Item $settingsPath -Force
    if ($fi.IsReadOnly) { $fi.IsReadOnly = $false }
    $json = $settings | ConvertTo-Json -Depth 10
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($settingsPath, $json, $utf8NoBom)

    Write-Host ""
    Write-Host "[OK] Additive install complete."
    Write-Host "     Commands target: $dstDir"
    Write-Host "     Events target  : $dstEventsDir"
    Write-Host "     settings.json: ScriptsDir untouched, Python.Path + Python.Commands + Python.Events extended."
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart Cascadeur."
Write-Host "  2. Open Commands menu - should see Poppet entries."
Write-Host "  3. Verify Qt integration: Commands -> Poppet -> POC Tick Loop"
Write-Host "  4. Start the real server: Commands -> Poppet -> Start Server"
Write-Host "  5. From a terminal: python .\scripts\poc_client.py"
