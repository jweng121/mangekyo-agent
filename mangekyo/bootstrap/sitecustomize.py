"""Python's opt-in startup hook for projects added with Mangekyo."""

import os

if os.environ.get("MANGEKYO_AUTO_TRACE") == "python-langchain-auto":
    try:
        from mangekyo.autotrace import install

        install()
    except Exception as exc:  # Instrumentation must not prevent the agent from starting.
        import sys
        try:
            from mangekyo.capture import record_capture_failure
            record_capture_failure("startup", exc)
        except Exception:
            # The SDK itself may be unavailable in this interpreter.
            import json
            path = os.environ.get("MANGEKYO_CAPTURE_FAILURES")
            if path:
                try:
                    with open(path, "a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"stage": "startup",
                                                 "error_type": type(exc).__name__}) + "\n")
                except OSError:
                    pass

        print(f"Mangekyo automatic tracing unavailable: {exc}", file=sys.stderr)
