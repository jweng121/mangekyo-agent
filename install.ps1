param(
    [string]$ReleaseBaseUrl = '',
    [string]$ReleaseApiUrl = 'https://api.github.com/repos/jweng121/mangekyo-agent/releases?per_page=100',
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Mangekyo\bin'),
    [switch]$SkipPath,
    [switch]$NoPrompt,
    [switch]$LaunchTui
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$assetName = 'mangekyo-windows-x64.exe'
if ($ReleaseBaseUrl) {
    $releaseBase = $ReleaseBaseUrl.TrimEnd('/')
    $checksumUrl = "$releaseBase/SHA256SUMS.txt"
    $downloadUrl = "$releaseBase/$assetName"
} else {
    $releases = Invoke-RestMethod -Uri $ReleaseApiUrl -Headers @{
        Accept = 'application/vnd.github+json'
        'User-Agent' = 'MangekyoInstaller'
    }
    $eligible = foreach ($release in $releases) {
        if ($release.draft -or -not $release.published_at) { continue }
        $checksumAsset = @($release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' })
        $binaryAsset = @($release.assets | Where-Object { $_.name -eq $assetName })
        if ($checksumAsset.Count -eq 1 -and $binaryAsset.Count -eq 1) {
            $release
        }
    }
    $selected = $eligible | Sort-Object { [DateTimeOffset]::Parse($_.published_at) } -Descending | Select-Object -First 1
    if (-not $selected) {
        throw 'No published Mangekyo release has both the Windows executable and SHA256SUMS.txt.'
    }
    $checksumUrl = ($selected.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' }).browser_download_url
    $downloadUrl = ($selected.assets | Where-Object { $_.name -eq $assetName }).browser_download_url
    Write-Host "Selected Mangekyo release $($selected.tag_name)"
}
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
    Write-Host "Downloading Mangekyo from $downloadUrl"
    Invoke-WebRequest -UseBasicParsing -Uri $checksumUrl -OutFile $checksumFile
    Invoke-WebRequest -UseBasicParsing -Uri $downloadUrl -OutFile $downloadFile

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

    Write-Host 'Quick start: initializing local history...'
    $setupOutput = & $downloadFile setup
    $setupExit = $LASTEXITCODE
    if ($setupExit -ne 0) {
        throw 'Mangekyo setup failed. Existing installation was left unchanged.'
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
    $setupOutput | Where-Object { $_ -notmatch '^Next:' } | ForEach-Object { Write-Host $_ }
    if ($SkipPath) {
        Write-Host 'PATH was left unchanged for this test installation.'
    } else {
        Write-Host 'If this ran in a child PowerShell process, open a new terminal first.'
    }

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
} finally {
    if (Test-Path -LiteralPath $work) {
        Remove-Item -LiteralPath $work -Recurse -Force
    }
}
