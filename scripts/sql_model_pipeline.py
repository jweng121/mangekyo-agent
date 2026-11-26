"""Local train/evaluate/activate protocol for the contained SQL demo."""

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mangekyo.examples.sql_agent import choose_table


request = json.load(sys.stdin)
stage = sys.argv[1]
if stage == "trainer":
    table = request["commit"]["correction"]["selected_table"]
    artifact = Path("sql-model-v2.json")
    artifact.write_text(json.dumps({"version": "v2", "table_for_bookings": table}))
    print(json.dumps({"model_version": "v2", "candidate_artifact": str(artifact)}))
elif stage == "evaluator":
    artifact = request["candidate"]["candidate_artifact"]
    os.environ["MANGEKYO_SQL_MODEL"] = str(Path(artifact).resolve())
    common = {"schema": ["bookings", "invoices"]}
    committed = choose_table({**common, "question": "Count Toronto bookings"})["selected_table"]
    held_out = choose_table({**common, "question": "Count Toronto invoices"})["selected_table"]
    print(json.dumps({"model_version": request["candidate"]["model_version"],
                      "committed_case_passed": committed == "bookings",
                      "held_out_passed": held_out == "invoices", "held_out_count": 1}))
elif stage == "activator":
    shutil.copyfile(request["candidate"]["candidate_artifact"], "active-sql-model.json")
    active = json.loads(Path("active-sql-model.json").read_text())
    print(json.dumps({"active_version": active["version"],
                      "active_artifact": "active-sql-model.json"}))
