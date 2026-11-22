param(
    [string]$ReleaseBaseUrl = 'https://github.com/jweng121/mangekyo-agent/releases/latest/download',
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Mangekyo\bin'),
    [switch]$SkipPath
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$assetName = 'mangekyo-windows-x64.exe'
$releaseBase = $ReleaseBaseUrl.TrimEnd('/')
$destinationDir = [System.IO.Path]::GetFullPath($InstallDir)
$destination = Join-Path $destinationDir 'mangekyo.exe'
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$work = [System.IO.Path]::GetFullPath((Join-Path $tempRoot ('mangekyo-install-' + [guid]::NewGuid().ToString('N'))))
if (-not $work.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Installer temporary directory is outside the system temp directory.'
}

New-Item -ItemType Directory -Path $work -Force | Out-Null
try {
    $checksumFile = Join-Path $work 'SHA256SUMS.txt'
    $downloadFile = Join-Path $work $assetName
    Write-Host "Downloading Mangekyo from $releaseBase"
    Invoke-WebRequest -UseBasicParsing -Uri "$releaseBase/SHA256SUMS.txt" -OutFile $checksumFile
    Invoke-WebRequest -UseBasicParsing -Uri "$releaseBase/$assetName" -OutFile $downloadFile

    $checksumLines = @(Get-Content -LiteralPath $checksumFile | Where-Object {
        $_ -match ('^([0-9a-fA-F]{64})\s+\*?' + [regex]::Escape($assetName) + '$')
    })
    if ($checksumLines.Count -ne 1) {
        throw "Release checksum for $assetName is missing or ambiguous."
    }
    $expected = [regex]::Match($checksumLines[0], '^([0-9a-fA-F]{64})').Groups[1].Value
    $actual = (Get-FileHash -LiteralPath $downloadFile -Algorithm SHA256).Hash
    if (-not $actual.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Downloaded Mangekyo failed its SHA256 check. Installation stopped."
    }

    New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
    $staged = Join-Path $destinationDir ('mangekyo-' + [guid]::NewGuid().ToString('N') + '.exe')
    $backup = Join-Path $destinationDir ('mangekyo-backup-' + [guid]::NewGuid().ToString('N') + '.exe')
    Copy-Item -LiteralPath $downloadFile -Destination $staged
    try {
        if (Test-Path -LiteralPath $destination) {
            [System.IO.File]::Replace($staged, $destination, $backup)
        } else {
            [System.IO.File]::Move($staged, $destination)
        }
    } catch {
        Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
        throw "Could not replace $destination. Close Mangekyo and retry. $($_.Exception.Message)"
    }
    if (-not (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.Equals(
        $expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Installed Mangekyo failed its SHA256 check: $destination"
    }
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue

    if (-not $SkipPath) {
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
            [Environment]::SetEnvironmentVariable('Path', ((@($entries) + $destinationDir) -join ';'), 'User')
        }
        if (-not (($env:Path -split ';') | Where-Object {
            $_.Trim().TrimEnd('\').Equals($destinationDir.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
        })) {
            $env:Path = "$env:Path;$destinationDir"
        }
    }

    Write-Host "Mangekyo installed: $destination"
    if ($SkipPath) {
        Write-Host 'PATH was left unchanged for this test installation.'
    } else {
        Write-Host 'Run: mangekyo setup'
        Write-Host 'If this ran in a child PowerShell process, open a new terminal first.'
    }
} finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
