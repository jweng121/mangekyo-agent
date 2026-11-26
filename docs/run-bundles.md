# Portable run bundles

A run bundle carries one root run and its child runs, checkpoints, branches,
events, actions, evidence files, and annotations without changing Mangekyo's
local event format. Every object and evidence blob is checked against its
SHA256 hash on import. Importing the same bundle again is idempotent; a record
ID collision with different content is rejected.

```powershell
mangekyo --home .mangekyo bundle export RUN_ID run-history.json
mangekyo --home other-history bundle import run-history.json
mangekyo --home other-history dashboard
```

The export command refuses to overwrite an existing file. A bundle may contain
captured documents, page text, local paths, and other sensitive run context.
Inspect it before sharing. Configure `MANGEKYO_REDACT` when the source run is
captured; import is refused while redaction is configured because changing
captured bytes during import would invalidate their hashes.

Bundles are a local transport format for the optional [self-hosted team
API](team-sharing.md). They do not carry a running environment or LangGraph's
checkpoint database, so imported runs are for inspection and review, not
remote live resume.
