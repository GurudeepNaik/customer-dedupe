import csv
import io

import pytest
from fastapi.testclient import TestClient

from customer_dedupe.api import Settings, create_app

CSV = """ContactId,First,Last,Email,Phone,Street,Zip
1,Robert,Smith,bob.smith@gmail.com,816-517-2606,12 Oak Street,64111
2,Bob,SMITH,BobSmith+x@gmail.com,(816) 517 2606,12 Oak St,64111-1234
3,Chloe,Smith,,816-517-2606,12 Oak Street,64111
4,=HYPERLINK("x"),Lee,,,,
"""
MAPPING = (
    '{"id": "ContactId", "first_name": "First", "last_name": "Last", "email": "Email",'
    ' "phone": "Phone", "street": "Street", "postal_code": "Zip"}'
)


@pytest.fixture
def client(tmp_path) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(Settings(database_url=f"sqlite:///{tmp_path / 't.db'}")))


def upload(client: TestClient, text: str = CSV, mapping: str = MAPPING):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/jobs", files={"file": ("c.csv", text)}, data={"mapping": mapping, "name": "t"}
    )


def test_upload_clusters_and_merge_plan(client: TestClient) -> None:
    resp = upload(client)
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["stats"]["records"] == 4

    [cluster] = client.get(f"/api/jobs/{job['id']}/clusters").json()["items"]
    assert sorted(m["id"] for m in cluster["members"]) == ["1", "2"]
    assert cluster["golden"]["first_name"]["value"] == "Robert"

    plan = list(
        csv.DictReader(io.StringIO(client.get(f"/api/jobs/{job['id']}/merge-plan.csv").text))
    )
    assert len(plan) == 4  # every record appears exactly once
    assert sum(r["survivor"] == "true" for r in plan) == 3  # 3 customers
    assert any(r["first_name"].startswith("'=") for r in plan)  # formula neutralised


def test_review_decision_feeds_the_next_run(client: TestClient) -> None:
    text = (
        "id,first_name,last_name,phone,street,postal_code\n"
        "a,Mark,Lee,3035550100,5 Elm St,80202\n"
        "b,Marc,Lee,3035550100,5 Elm St,80202\n"
    )
    job = upload(client, text, "{}").json()
    review = client.get(f"/api/jobs/{job['id']}/review").json()
    assert review["total"] == 1 and review["items"][0]["priority"] == "high"

    ok = client.post(f"/api/jobs/{job['id']}/decisions", json={"a": "b", "b": "a", "same": True})
    assert ok.status_code == 204
    assert client.get(f"/api/jobs/{job['id']}/review").json()["items"][0]["decided"] is True

    rerun = client.post(f"/api/jobs/{job['id']}/rerun").json()
    assert rerun["decisions_applied"] == 1
    assert client.get(f"/api/jobs/{rerun['id']}/clusters").json()["total"] == 1
    assert client.get(f"/api/jobs/{rerun['id']}/review").json()["total"] == 0


def test_demo_job_reports_accuracy(client: TestClient) -> None:
    job = client.post("/api/jobs/demo").json()
    assert job["evaluation"]["precision"] >= 0.995
    assert client.get("/api/jobs/demo-is-not-an-id").status_code == 404


def test_same_file_reuses_the_dataset(client: TestClient) -> None:
    first, second = upload(client).json(), upload(client).json()
    assert first["dataset_id"] == second["dataset_id"] and first["id"] != second["id"]


@pytest.mark.parametrize(
    ("text", "mapping"),
    [
        ("x,y\n1,2\n", "{}"),  # no id column
        (CSV, '{"nope": "x"}'),  # unknown field
        (CSV, "[1]"),  # not an object
        ("id\n1\n1\n", "{}"),  # duplicate ids
    ],
)
def test_rejects_bad_input(client: TestClient, text: str, mapping: str) -> None:
    assert upload(client, text, mapping).status_code == 422


def test_decision_must_reference_dataset_records(client: TestClient) -> None:
    job = upload(client).json()
    resp = client.post(
        f"/api/jobs/{job['id']}/decisions", json={"a": "1", "b": "999", "same": False}
    )
    assert resp.status_code == 404
