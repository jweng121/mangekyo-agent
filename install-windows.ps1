param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Mangekyo\bin'),
    [switch]$NoPrompt,
    [switch]$LaunchTui
)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'dist\mangekyo.exe'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Mangekyo executable is missing: $source. Build it with python scripts/build_standalone.py first."
}
Write-Host 'Quick start: initializing local history...'
$setupOutput = & $source setup
$setupExit = $LASTEXITCODE
if ($setupExit -ne 0) {
    throw 'Mangekyo setup failed. Existing installation was left unchanged.'
}

$destinationDir = [System.IO.Path]::GetFullPath($InstallDir)
New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
$destination = Join-Path $destinationDir 'mangekyo.exe'
try {
    Copy-Item -LiteralPath $source -Destination $destination -Force
} catch {
    throw "Could not replace $destination. Close any running Mangekyo dashboard or TUI and retry. $($_.Exception.Message)"
}

$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
$installedHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
if ($sourceHash -ne $installedHash) {
    throw "The installed executable did not match the build artifact: $destination"
}

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$entries = @($userPath -split ';' | Where-Object { $_.Trim() })
$alreadyPresent = $false
foreach ($entry in $entries) {
    $expanded = [Environment]::ExpandEnvironmentVariables($entry.Trim().TrimEnd('\'))
    if ($expanded.Equals($destinationDir.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        $alreadyPresent = $true
        break
    }
}
if (-not $alreadyPresent) {
    $updatedPath = (@($entries) + $destinationDir) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $updatedPath, 'User')
}

if (-not (($env:Path -split ';') | Where-Object {
    $_.Trim().TrimEnd('\').Equals($destinationDir.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
})) {
    $env:Path = "$env:Path;$destinationDir"
}

Write-Host "Mangekyo installed: $destination"
$setupOutput | Where-Object { $_ -notmatch '^Next:' } | ForEach-Object { Write-Host $_ }
Write-Host "User PATH includes: $destinationDir"
Write-Host 'For an already open PowerShell, run: $env:Path += ";$env:LOCALAPPDATA\Mangekyo\bin"'
Write-Host 'Restart VS Code or Windows Terminal to load the permanent PATH change automatically.'
$startTui = [bool]$LaunchTui
if (-not $startTui -and -not $NoPrompt -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    $answer = Read-Host 'Open the Mangekyo terminal inspector now? [y/N]'
    $startTui = $answer -match '^(y|yes)$'
}
if ($startTui) {
    & $destination --tui
    if ($LASTEXITCODE -ne 0) {
        throw 'The Mangekyo terminal inspector exited with an error. Run mangekyo doctor for details.'
    }
} else {
    Write-Host 'Next: mangekyo demo, then mangekyo --tui'
}
