"""Credential-free Cloud Run plan for the synthetic public demo.

This module never calls gcloud or a Google API.  It keeps the proposed target
and its approval gates inspectable before any billable or public resource is
created.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.web.deployment import validate_source_repository_url

_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_SERVICE_NAME = re.compile(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class CloudRunPublicDemoPlan:
    """Fail-closed deployment target agreed for the public synthetic UI."""

    project_id: str = "ride-storyteller"
    region: str = "asia-northeast1"
    service_name: str = "ride-storyteller-public-demo"
    repository_name: str = "ride-storyteller"
    image_name: str = "public-demo"
    image_tag: str = "candidate"
    service_account_name: str = "ride-storyteller-public"
    cpu: int = 1
    memory: str = "512Mi"
    min_instances: int = 0
    max_instances: int = 1
    concurrency: int = 4
    timeout_s: int = 30
    health_path: str = "/health"
    source_repository_url: str | None = None

    def __post_init__(self) -> None:
        if not _PROJECT_ID.fullmatch(self.project_id):
            raise ValueError("project_id must be a valid Google Cloud project ID")
        if self.region != "asia-northeast1":
            raise ValueError("the approved public-demo region is asia-northeast1")
        for label, value in (
            ("service_name", self.service_name),
            ("repository_name", self.repository_name),
            ("image_name", self.image_name),
            ("service_account_name", self.service_account_name),
        ):
            if not _SERVICE_NAME.fullmatch(value):
                raise ValueError(f"{label} must be a valid lowercase resource name")
        if not self.image_tag or any(character.isspace() for character in self.image_tag):
            raise ValueError("image_tag must be non-empty and contain no whitespace")
        if self.cpu != 1 or self.memory != "512Mi":
            raise ValueError("the reviewed public-demo size is 1 CPU and 512Mi")
        if self.min_instances != 0 or self.max_instances != 1:
            raise ValueError("the public demo must scale from zero to at most one instance")
        if not 1 <= self.concurrency <= 4:
            raise ValueError("concurrency must stay between one and four")
        if not 1 <= self.timeout_s <= 30:
            raise ValueError("timeout_s must stay between one and 30 seconds")
        if self.health_path != "/health":
            raise ValueError("the Cloud Run health path must be /health")
        if self.source_repository_url is not None:
            validate_source_repository_url(self.source_repository_url)

    @property
    def image_uri(self) -> str:
        return (
            f"{self.region}-docker.pkg.dev/{self.project_id}/{self.repository_name}/"
            f"{self.image_name}:{self.image_tag}"
        )

    @property
    def service_account(self) -> str:
        return f"{self.service_account_name}@{self.project_id}.iam.gserviceaccount.com"

    @property
    def environment(self) -> tuple[tuple[str, str], ...]:
        values = (
            ("RIDE_WEB_MODE", "public_demo"),
            ("RIDE_WEB_HOST", "0.0.0.0"),
            ("RIDE_UI_DEFAULT_LANGUAGE", "en"),
            ("WEB_CONCURRENCY", "2"),
            ("WEB_THREADS", "2"),
        )
        if self.source_repository_url is None:
            return values
        return (*values, ("RIDE_SOURCE_REPOSITORY_URL", self.source_repository_url))

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "region": self.region,
            "service_name": self.service_name,
            "repository_name": self.repository_name,
            "image_uri": self.image_uri,
            "service_account": self.service_account,
            "cpu": self.cpu,
            "memory": self.memory,
            "min_instances": self.min_instances,
            "max_instances": self.max_instances,
            "concurrency": self.concurrency,
            "timeout_s": self.timeout_s,
            "health_path": self.health_path,
            "source_repository_configured": self.source_repository_url is not None,
            "ingress": "all",
            "environment": dict(self.environment),
            "deployment_approved": False,
            "public_access_approved": False,
            "mutation_performed": False,
        }

    def gcloud_deploy_arguments(
        self,
        *,
        deployment_approved: bool,
        public_access_approved: bool,
    ) -> tuple[str, ...]:
        """Return arguments only after the resource-creation gate is explicit.

        Building these arguments still performs no external action.  Public IAM
        access is a separate gate from creating the private service.
        """

        if not deployment_approved:
            raise PermissionError("Cloud Run resource creation is not approved")
        if public_access_approved and self.source_repository_url is None:
            raise PermissionError(
                "public access requires a validated public source repository URL"
            )
        public_flag = (
            "--allow-unauthenticated"
            if public_access_approved
            else "--no-allow-unauthenticated"
        )
        environment = ",".join(f"{name}={value}" for name, value in self.environment)
        return (
            "gcloud",
            "run",
            "deploy",
            self.service_name,
            f"--project={self.project_id}",
            f"--region={self.region}",
            "--platform=managed",
            f"--image={self.image_uri}",
            f"--service-account={self.service_account}",
            f"--cpu={self.cpu}",
            f"--memory={self.memory}",
            f"--min={self.min_instances}",
            f"--max={self.max_instances}",
            f"--concurrency={self.concurrency}",
            f"--timeout={self.timeout_s}",
            "--port=8080",
            (
                "--startup-probe="
                f"httpGet.path={self.health_path},httpGet.port=8080,"
                "initialDelaySeconds=0,timeoutSeconds=3,periodSeconds=10,"
                "failureThreshold=3"
            ),
            "--ingress=all",
            f"--set-env-vars={environment}",
            public_flag,
        )


def main() -> None:
    """Print the reviewed plan without credentials, network calls, or mutation."""

    print(json.dumps(CloudRunPublicDemoPlan().to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
