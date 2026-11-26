"""Run the contained SQL LangGraph agent under ``mangekyo run``."""

import json
import os
import uuid
import hashlib
from pathlib import Path

from mangekyo.langgraph_api import LangGraphApi
from mangekyo.store import Store


def _pdf_input(project: Path) -> tuple[dict, bytes | None, str | None]:
    path = project / "booking-request.pdf"
    if not path.is_file():
        return {"question": "Count Toronto bookings"}, None, None
    import pypdfium2 as pdfium

    data = path.read_bytes()
    document = pdfium.PdfDocument(data)
    try:
        parsed_text = "\n".join(page.get_textpage().get_text_range() for page in document)
    finally:
        document.close()
    question = next((line.partition(":")[2].strip() for line in parsed_text.splitlines()
                     if line.startswith("Question:")), None)
    if not question:
        raise ValueError("Mock PDF is missing its Question field")
    return {"question": question, "parsed_document_text": parsed_text,
            "source_document": str(path.resolve()),
            "source_document_sha256": hashlib.sha256(data).hexdigest()}, data, parsed_text


def main() -> None:
    project = Path.cwd()
    config = json.loads((project / ".mangekyo-agent.json").read_text(encoding="utf-8"))
    os.environ["MANGEKYO_SQL_MODEL"] = str(project / config["current_model"]["artifact"])
    # The API adapter owns graph events when it is used inside a launched process.
    os.environ["MANGEKYO_API_MANAGED"] = "1"
    api = LangGraphApi(Path(os.environ["MANGEKYO_HOME"]))
    input_state, pdf_bytes, parsed_text = _pdf_input(project)
    _, registered = api.post("/api/v1/langgraph/runs", {
        "graph": "sql", "task_id": "sql-cli-demo", "thread_id": uuid.uuid4().hex,
        "label": "Count Toronto bookings", "input": input_state})
    if pdf_bytes is not None:
        with Store(Path(os.environ["MANGEKYO_HOME"])) as store:
            read_event = store.event(registered["run_id"], "read", {
                "name": "parse_booking_pdf", "path": input_state["source_document"],
                "question": input_state["question"], "parsed_text": parsed_text})
            store.artifact(registered["run_id"], "booking-request.pdf", pdf_bytes,
                           "application/pdf", event_id=read_event, parsed_text=parsed_text,
                           source="agent parsed PDF")
    _, result = api.post(f"/api/v1/langgraph/runs/{registered['run_id']}/execute", {})
    print(json.dumps({"run_id": registered["run_id"], "output": result["output"]}))


if __name__ == "__main__":
    main()
