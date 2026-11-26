param(
    [Parameter(Mandatory = $true)]
    [string]$Executable
)

$ErrorActionPreference = 'Stop'
$target = (Resolve-Path -LiteralPath $Executable).Path
$encoded = $env:WINDOWS_SIGNING_PFX_BASE64
$password = $env:WINDOWS_SIGNING_PFX_PASSWORD
if ([string]::IsNullOrWhiteSpace($encoded) -or [string]::IsNullOrWhiteSpace($password)) {
    throw 'A trusted Windows code-signing PFX and password are required before publishing a Windows release.'
}

$sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
$signTool = Get-ChildItem -LiteralPath $sdkRoot -Filter signtool.exe -Recurse -File |
    Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if (-not $signTool) {
    throw 'Windows SDK SignTool was not found on the release runner.'
}

$pfxPath = Join-Path $env:RUNNER_TEMP ('mangekyo-signing-' + [guid]::NewGuid().ToString('N') + '.pfx')
try {
    [System.IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($encoded))
    & $signTool.FullName sign /f $pfxPath /p $password /fd SHA256 `
        /tr http://timestamp.digicert.com /td SHA256 $target
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool signing failed with exit code $LASTEXITCODE"
    }
    & $signTool.FullName verify /pa /v $target
    if ($LASTEXITCODE -ne 0) {
        throw "SignTool verification failed with exit code $LASTEXITCODE"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $target
    if ($signature.Status -ne 'Valid') {
        throw "Windows signature status is $($signature.Status)"
    }
    Write-Host "Verified Windows code signature: $($signature.SignerCertificate.Subject)"
} finally {
    if (Test-Path -LiteralPath $pfxPath) {
        Remove-Item -LiteralPath $pfxPath -Force
    }
}
