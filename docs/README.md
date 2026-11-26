# Documentation

Mangekyo Agent records local execution history and supports recovery through compatible runtime adapters. Start with the [reference workflow](example-workflow.md) to inspect a failed simulation, branch at its checkpoint, resume, and compare the result. The [LangGraph evaluation](langgraph-evaluation.md) covers a file-backed integration, the model-backed invoice example, its safety contract, and a measured Claude cost comparison.

The [main README](../README.md) has installation instructions, the CLI and dashboard quick start, SDK examples, and current platform limits. The [asset guide](../assets/README.md) identifies the terminal, dashboard, and GitHub artwork.

The [browser target example](browser-target.md) captures a real local page and highlights the element used by an agent decision.

The [capture and recovery contract](capture-and-recovery.md) explains per-run capture gaps, optional batch output capture, and live resume safety checks.

The [fresh-project onboarding check](first-user-journey.md) records a clean wheel installation and a run of an unchanged agent function from another project, including the capture and resume limits it exposed.

The [scale and privacy limits](scale-and-privacy.md) document local measurements, storage growth, output and evidence caps, and redaction boundaries.

[Portable run bundles](run-bundles.md) preserve a run family's local event format for transfer and later server ingestion.

The optional [team sharing API](team-sharing.md) ingests those bundles into authenticated workspaces for evidence-linked review and correction proposals.

The proposed beta [release notes](release-notes-v0.2.0-beta.1.md) summarize the recovery flow and its measured model-backed result.

The [Windows release guide](windows-release.md) explains the required code-signing gate and local verification status.

The [Linux release guide](linux-release.md) covers the Ubuntu WSL standalone build, local installer, and verification scope.

The [macOS release preparation](macos-release.md) records the native validation job and current distribution gap.

The [PyPI package preparation](pypi-release.md) describes the local wheel and source archive checks and the account-side trusted publisher setup.

The project is licensed under [Apache 2.0](../LICENSE) and maintained at [GitHub](https://github.com/jweng121/mangekyo-agent).

## Language

The documentation is currently in English. The Python SDK supports Python 3.11 or newer. Local standalone installers exist for Windows and Linux; the Linux build has been verified on Ubuntu under WSL, and neither platform release has been published.
