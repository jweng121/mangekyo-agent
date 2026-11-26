# Current scale and privacy limits

Mangekyo keeps its local metadata in SQLite WAL mode and its immutable JSON
objects and evidence blobs under the selected store directory. It does not
automatically delete runs, snapshots, or blobs. `mangekyo cache stats` shows
physical object and artifact bytes; operators must plan retention and backups
for always-on capture. The local dashboard currently loads a run's complete
event list, so very long runs have no incremental browsing guarantee.
There is no selective run deletion command. Removing a store directory removes
all of its runs and evidence; stop all writers and retain any needed backup
before doing so. A copied export bundle has its own copy of saved data and is
not affected when the local store is removed.

## Measured local envelope

On this Windows development checkout, `python scripts/measure_store_scale.py
--home .test-scale-5000 --events 5000` wrote 5,000 small observations in
25.126 seconds, reopened and built the capture report in 2.125 seconds, and
returned `PRAGMA integrity_check = ok`. The content-addressed objects occupied
1,618,890 bytes. A separate test had six independent store connections write
300 events into one run and verified contiguous, unique sequence numbers.
These are local measurements, not a throughput promise for other disks or
platforms. The probe requires a new store path and never deletes existing
history.

Each evidence file is limited to 50 MB. Optional `run --capture-output` keeps
at most 256 KB each of stdout and stderr while forwarding the full streams to
the terminal; the saved event records whether either stream was truncated.
Ordinary model and tool event payloads do not yet have a configured size cap.

## Sensitive data

`MANGEKYO_REDACT` replaces configured literal strings in JSON events and
snapshots **before** persistence. It is not a general secret detector. Raw
attached PDF and image bytes are stored as supplied; they are not pixel or
document redacted. Browser capture is disabled while literal redaction is set
because a text substitution cannot sanitize screenshot pixels. Inspect source
files and masks before attaching evidence. Batch output capture is opt-in
because stdout and stderr may contain credentials or personal data.

Run bundles include saved context, output, local paths, and raw evidence. They
are verified for integrity on import, not sanitized for sharing. Exporting a
bundle does not retroactively remove secrets. Keep the local store and exported
bundles under appropriate filesystem permissions and review a bundle before
uploading it to the optional team server.
