import json
import subprocess
import sys

import pytest

from app.web.cloud_run import CloudRunPublicDemoPlan


def test_cloud_run_plan_uses_approved_safe_defaults() -> None:
    plan = CloudRunPublicDemoPlan()

    assert plan.project_id == "ride-storyteller"
    assert plan.region == "asia-northeast1"
    assert plan.image_uri == (
        "asia-northeast1-docker.pkg.dev/ride-storyteller/"
        "ride-storyteller/public-demo:candidate"
    )
    assert plan.cpu == 1
    assert plan.memory == "512Mi"
    assert plan.min_instances == 0
    assert plan.max_instances == 1
    assert plan.concurrency == 4
    assert plan.health_path == "/health"
    assert plan.environment == (
        ("RIDE_WEB_MODE", "public_demo"),
        ("RIDE_WEB_HOST", "0.0.0.0"),
        ("RIDE_UI_DEFAULT_LANGUAGE", "en"),
        ("WEB_CONCURRENCY", "2"),
        ("WEB_THREADS", "2"),
    )


def test_cloud_run_plan_reports_no_approval_or_mutation() -> None:
    payload = CloudRunPublicDemoPlan().to_dict()

    assert payload["deployment_approved"] is False
    assert payload["public_access_approved"] is False
    assert payload["mutation_performed"] is False
    assert not any("KEY" in name or "TOKEN" in name for name in payload["environment"])


def test_cloud_run_arguments_require_explicit_deployment_approval() -> None:
    with pytest.raises(PermissionError, match="not approved"):
        CloudRunPublicDemoPlan().gcloud_deploy_arguments(
            deployment_approved=False,
            public_access_approved=False,
        )


def test_private_first_arguments_do_not_allow_unauthenticated_access() -> None:
    arguments = CloudRunPublicDemoPlan().gcloud_deploy_arguments(
        deployment_approved=True,
        public_access_approved=False,
    )

    assert "--no-allow-unauthenticated" in arguments
    assert "--allow-unauthenticated" not in arguments
    assert "--max=1" in arguments
    assert "--min=0" in arguments
    assert (
        "--startup-probe=httpGet.path=/health,httpGet.port=8080,"
        "initialDelaySeconds=0,timeoutSeconds=3,periodSeconds=10,"
        "failureThreshold=3"
    ) in arguments


def test_public_access_is_a_separate_explicit_argument() -> None:
    arguments = CloudRunPublicDemoPlan().gcloud_deploy_arguments(
        deployment_approved=True,
        public_access_approved=True,
    )

    assert "--allow-unauthenticated" in arguments
    assert "--no-allow-unauthenticated" not in arguments


@pytest.mark.parametrize(
    "changes",
    (
        {"region": "global"},
        {"cpu": 2},
        {"memory": "1Gi"},
        {"min_instances": 1},
        {"max_instances": 2},
        {"concurrency": 5},
        {"timeout_s": 31},
        {"health_path": "/healthz"},
    ),
)
def test_cloud_run_plan_rejects_unreviewed_capacity_or_region(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        CloudRunPublicDemoPlan(**changes)


def test_cloud_run_preflight_cli_is_local_json_only() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.web.cloud_run"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["mutation_performed"] is False
    assert payload["deployment_approved"] is False
    assert payload["public_access_approved"] is False
