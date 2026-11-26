"""Independent agent writers keep one ordered event stream."""

from concurrent.futures import ThreadPoolExecutor

from mangekyo.store import Store


def test_concurrent_writers_assign_unique_contiguous_event_order(tmp_path):
    home = tmp_path / "history"
    with Store(home) as store:
        run_id = store.create_run("parallel-agent", "shared run")

    def write_batch(worker: int) -> None:
        with Store(home) as store:
            for index in range(50):
                store.event(run_id, "tool", {"worker": worker, "index": index})

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(write_batch, range(6)))
    with Store(home) as store:
        events = store.events(run_id)
        assert len(events) == 300
        assert [event["seq"] for event in events] == list(range(1, 301))
        assert {(event["payload"]["worker"], event["payload"]["index"])
                for event in events} == {(worker, index) for worker in range(6)
                                      for index in range(50)}
