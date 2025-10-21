import nta_eval_svc.workers as workers_mod


def test_task_dispatch_invokes_delay(client, monkeypatch):
    calls = []

    def fake_delay(arg):
        calls.append(arg)
        return True

    # Patch the Celery task's delay method so we don't need a running worker
    monkeypatch.setattr(workers_mod.process_evaluation_job, "delay", fake_delay)

    job_id = "test-job-123"
    resp = client.post(f"/api/tasks/dispatch/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enqueued"] is True
    assert data["job_id"] == job_id
    assert calls == [job_id]
