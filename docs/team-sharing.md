# Optional team sharing

The team server accepts portable [run bundles](run-bundles.md) into named workspaces. Authorized clients can inspect the same run and its evidence, add evidence-linked comments, record review decisions, and propose correction branches. Bundle import preserves the local run event format. The server does not execute remote resumes.

## Configure users

Generate a long random token for each person and store its SHA-256 digest in a JSON file. For example, `python -c "import secrets; print(secrets.token_urlsafe(32))"` generates a token, and `python -c "from mangekyo.team import token_hash; import getpass; print(token_hash(getpass.getpass()))"` prints its digest without echoing it.

```json
{
  "users": [
    {"name": "alice", "workspace": "demo", "role": "editor", "token_sha256": "<64 lowercase hex characters>"},
    {"name": "bob", "workspace": "demo", "role": "reviewer", "token_sha256": "<another digest>"}
  ]
}
```

Roles are `viewer` (read runs and evidence), `editor` (also import bundles, comment, and propose corrections), `reviewer` (also approve or request changes and read the audit trail), and `admin` (all permissions). A token belongs to exactly one workspace. Keep tokens and the config file private. Each workspace has its own run store under the server root.

Start a loopback server:

```sh
mangekyo team --root ./team-data --config ./team-users.json
```

For access from another computer, use a TLS certificate and key and bind to a network address:

```sh
mangekyo team --root ./team-data --config ./team-users.json --host 0.0.0.0 --cert ./cert.pem --key ./key.pem
```

The server refuses non-loopback binding without TLS. Put it behind your normal network access controls and back up the server root. The JSON config is loaded at server startup; restart to change users or revoke a token.

To check the network path locally on a machine with OpenSSL, run `python scripts/smoke_team_tls.py` from the repository. It starts a TLS listener, uploads a run from one client process, then reads, comments on, and reviews its evidence from two client processes. It verifies the audit trail and confirms that a third workspace token is denied. This checks separate processes over TCP; a test from two physical computers is still needed before claiming that acceptance criterion is verified.

## Share and review a run

Export a run locally, then upload its bundle with an editor token:

```sh
mangekyo bundle export RUN_ID run.json
curl -X POST http://127.0.0.1:8780/v1/workspaces/demo/bundles -H "Authorization: Bearer $TEAM_TOKEN" -H "Content-Type: application/json" --data-binary @run.json
```

Clients use the same bearer header for these routes:

| Method | Route suffix after `/v1/workspaces/demo` | Role |
| --- | --- | --- |
| GET | `/runs`, `/runs/RUN_ID`, `/runs/RUN_ID/artifacts/ARTIFACT_ID` (original bytes) | viewer |
| GET | `/runs/RUN_ID/artifacts/ARTIFACT_ID/detail` (parsed text and annotations) | viewer |
| GET | `/runs/RUN_ID/comments`, `/runs/RUN_ID/reviews` | viewer |
| GET | `/audit` | reviewer |
| POST | `/bundles` | editor |
| POST | `/runs/RUN_ID/comments` with `{"artifact_id":"...","text":"..."}` | editor |
| POST | `/runs/RUN_ID/reviews` with `{"artifact_id":"...","decision":"approved","note":"..."}` | reviewer |
| POST | `/runs/RUN_ID/corrections` with `{"snapshot_id":"...","name":"...","correction":{"replacement":"safe"}}` | editor |

Review decisions also accept `changes_requested`. Corrections create a branch in the shared store and write an audit entry; an operator still resumes it locally through the normal compatibility and side-effect checks. Bundle ingestion, comments, decisions, and proposed corrections are audited. This is an initial self-hosted API; it has no browser team dashboard or hosted account management.
