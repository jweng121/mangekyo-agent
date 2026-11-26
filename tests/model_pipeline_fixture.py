"""Tiny user-owned train/evaluate/activate pipeline for contract testing."""

import json
import os
import shutil
import sys
from pathlib import Path

request = json.load(sys.stdin)
stage = sys.argv[1]

if stage == "trainer":
    replacement = request["commit"]["correction"]["replacement"]
    candidate = Path("candidate-model.json")
    if os.environ.get("MANGEKYO_TEST_UNCHANGED_MODEL") == "1":
        shutil.copyfile(request["current_model"]["artifact"], candidate)
    else:
        candidate.write_text(json.dumps({"version": "v2", "mapping": {"unsafe": replacement}}))
    print(json.dumps({"model_version": "v2", "candidate_artifact": str(candidate)}))
elif stage == "evaluator":
    model = json.loads(Path(request["candidate"]["candidate_artifact"]).read_text())
    mapping = model["mapping"]
    print(json.dumps({"model_version": model["version"],
                      "committed_case_passed": mapping.get("unsafe") == "safe",
                      "held_out_passed": (mapping.get("untouched", "untouched") == "untouched"
                                          and os.environ.get("MANGEKYO_TEST_EVAL_FAIL") != "1"),
                      "held_out_count": 1}))
elif stage == "activator":
    shutil.copyfile(request["candidate"]["candidate_artifact"], "active-model.json")
    active = json.loads(Path("active-model.json").read_text())
    print(json.dumps({"active_version": active["version"],
                      "active_artifact": "active-model.json"}))
