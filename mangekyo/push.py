"""Run a user-owned model improvement pipeline without a Mangekyo model service."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .commits import read_commit
from .project import CONFIG
from .store import Store


def _command(project: Path, argv: Any, request: dict[str, Any], stage: str) -> dict[str, Any]:
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError(f"push.{stage} must be a nonempty argument list")
    completed = subprocess.run(argv, cwd=project, input=json.dumps(request), text=True,
                               capture_output=True, timeout=600, check=False)
    if completed.returncode:
        raise RuntimeError(f"{stage} failed (exit {completed.returncode}): {completed.stderr[-500:]}")
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{stage} must return one JSON object on stdout") from exc
    if not isinstance(response, dict):
        raise ValueError(f"{stage} must return one JSON object on stdout")
    return response


def _artifact(project: Path, value: Any, stage: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{stage} must return an artifact path")
    path = (project / value).resolve()
    if not path.is_relative_to(project) or not path.is_file():
        raise ValueError(f"{stage} artifact must be a file inside the project")
    return path


def push_commit(store: Store, commit_id: str, project: Path) -> dict[str, Any]:
    project = project.expanduser().resolve()
    config_path = project / CONFIG
    if not config_path.is_file():
        raise ValueError(f"Run mangekyo add {project} before push")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    pipeline = config.get("push")
    if not isinstance(pipeline, dict):
        raise ValueError("Configure push trainer, evaluator, and activator in project config")
    commit = read_commit(store, commit_id)
    current = config.get("current_model") or {}
    if not isinstance(current, dict):
        raise ValueError("current_model must be an object")
    if not isinstance(current.get("version"), str):
        raise ValueError("Configure current_model.version and current_model.artifact before push")
    previous = _artifact(project, current.get("artifact"), "Current model")
    previous_hash = hashlib.sha256(previous.read_bytes()).hexdigest()
    request = {"commit_id": commit_id, "commit": commit,
               "current_model": current}
    trained = _command(project, pipeline.get("trainer"), request, "trainer")
    version = trained.get("model_version")
    artifact = trained.get("candidate_artifact")
    if not isinstance(version, str) or not version.strip() or not isinstance(artifact, str):
        raise ValueError("Trainer must return model_version and candidate_artifact")
    if version == current.get("version"):
        raise ValueError("Trainer did not produce a new model version")
    candidate = _artifact(project, artifact, "Candidate")
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if previous_hash == candidate_hash:
        raise ValueError("Trainer returned unchanged model contents")
    evaluation = _command(project, pipeline.get("evaluator"),
                          {**request, "candidate": trained, "candidate_sha256": candidate_hash},
                          "evaluator")
    if (evaluation.get("model_version") != version or
            evaluation.get("committed_case_passed") is not True or
            evaluation.get("held_out_passed") is not True or
            not isinstance(evaluation.get("held_out_count"), int) or
            evaluation["held_out_count"] < 1):
        raise ValueError("Candidate did not pass the committed and held-out evals")
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != candidate_hash:
        raise ValueError("Candidate changed during evaluation")
    activated = _command(project, pipeline.get("activator"),
                         {**request, "candidate": trained, "candidate_sha256": candidate_hash,
                          "evaluation": evaluation}, "activator")
    if activated.get("active_version") != version:
        raise ValueError("Activator did not confirm the new active model version")
    active = _artifact(project, activated.get("active_artifact"), "Active model")
    if hashlib.sha256(active.read_bytes()).hexdigest() != candidate_hash:
        raise ValueError("Active model does not match the evaluated candidate")
    config["current_model"] = {"version": version, "artifact": str(active.relative_to(project)),
                               "sha256": candidate_hash}
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    result = {"commit_id": commit_id, "model_version": version,
              "candidate_artifact": str(candidate), "candidate_sha256": candidate_hash,
              "evaluation": evaluation, "activation": activated}
    store.put(result)
    store.event(commit["corrected_run"], "model_push", result)
    return result
