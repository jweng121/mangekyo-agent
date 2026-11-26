# Windows release signing

The Windows release workflow builds a standalone executable, signs it, verifies its Authenticode signature, runs recovery, real ConPTY terminal UI, browser, project setup, and installer smoke checks, and only then prepares the checksum and release assets. The checksum covers the final signed bytes. A missing or invalid signature stops the workflow before publication.

The workflow expects two repository secrets:

- `WINDOWS_SIGNING_PFX_BASE64`: Base64 encoding of a PFX containing a code-signing certificate from a provider trusted by Windows.
- `WINDOWS_SIGNING_PFX_PASSWORD`: Password for that PFX.

The signing script writes the PFX only to the runner's temporary directory and removes it after signing. It uses Windows SDK SignTool with SHA-256 and an RFC 3161 timestamp, then runs `signtool verify /pa` and checks `Get-AuthenticodeSignature` for `Valid`. It does not print either secret. The release job treats SignTool warnings as failures.

Microsoft's [Smart App Control guidance](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/smart-app-control) recommends a trusted code-signing certificate for distributed binaries. See [SignTool's signing and verification options](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool) for the command flags used by the script.

Before a Windows beta can be published, run the release workflow with a trusted certificate and verify the signed executable on a machine with Smart App Control enabled. An earlier unsigned local build was blocked by Smart App Control. The current unsigned build passed local packaged and installer smoke checks, but those results do not establish that the final signed build will run on protected machines.
