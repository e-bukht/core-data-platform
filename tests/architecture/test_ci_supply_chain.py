from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:"
    start = workflow.index(marker)

    next_job = workflow.find("\n  ", start + len(marker))

    while next_job != -1:
        candidate_end = workflow.find(":", next_job + 3)

        if candidate_end != -1:
            candidate = workflow[next_job + 3 : candidate_end]

            if (
                candidate
                and "\n" not in candidate
                and candidate.strip() == candidate
            ):
                return workflow[start:next_job]

        next_job = workflow.find("\n  ", next_job + 3)

    return workflow[start:]


def test_release_runs_only_after_certification_with_isolated_privileges() -> None:
    workflow = _workflow_text()

    top_level_permissions = """permissions:
  contents: read
"""

    assert top_level_permissions in workflow

    certification = _job_block(
        workflow,
        "certification",
    )

    for dependency in (
        "quality",
        "postgres-matrix",
        "tenant-isolation",
    ):
        assert dependency in certification

    release = _job_block(
        workflow,
        "release",
    )

    assert "needs: certification" in release
    assert "github.event_name == 'push'" in release
    assert "github.ref == 'refs/heads/main'" in release

    for required_permission in (
        "contents: read",
        "id-token: write",
        "attestations: write",
        "artifact-metadata: write",
    ):
        assert required_permission in release

    pre_release = workflow[: workflow.index("  release:")]

    for privileged_permission in (
        "id-token: write",
        "attestations: write",
        "artifact-metadata: write",
    ):
        assert privileged_permission not in pre_release


def test_release_artifact_is_commit_bound_sbom_bound_and_attested() -> None:
    release = _job_block(
        _workflow_text(),
        "release",
    )

    required_fragments = (
        "SOURCE_SHA: ${{ github.sha }}",
        "ref: ${{ github.sha }}",
        'test "$(git rev-parse HEAD)" = "$SOURCE_SHA"',
        "uv build --wheel --out-dir dist",
        "core-data-platform-${VERSION}-${SOURCE_SHA}",
        "--format cyclonedx1.5",
        '"source_commit": os.environ["SOURCE_SHA"]',
        '"sha256": os.environ["WHEEL_SHA256"]',
        '"sha256": os.environ["SBOM_SHA256"]',
        "actions/attest@v4.2.2",
        "sbom-path: .release/runtime.cdx.json",
        '--source-digest "$SOURCE_SHA"',
        '--signer-digest "$SOURCE_SHA"',
        "--source-ref refs/heads/main",
        '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/ci.yml"',
        "--deny-self-hosted-runners",
        "--predicate-type https://cyclonedx.org/bom",
        "overwrite: false",
        "dist/*.whl",
        ".release/runtime.cdx.json",
        ".release/release-manifest.json",
        ".release/SHA256SUMS.txt",
        ".release/provenance.sigstore.json",
        ".release/sbom.sigstore.json",
    )

    for fragment in required_fragments:
        assert fragment in release

    ordered_steps = (
        "- name: Checkout certified source",
        "- name: Verify checked-out commit",
        "- name: Build immutable wheel",
        "- name: Resolve release identity",
        "- name: Generate release CycloneDX SBOM",
        "- name: Create release manifest and immutable digests",
        "- name: Record SHA256SUMS",
        "- name: Attest build provenance",
        "- name: Attest CycloneDX SBOM",
        "- name: Preserve attestation bundles",
        "- name: Verify provenance and SBOM attestations",
        "- name: Smoke-test built wheel",
        "- name: Upload immutable commit-addressable release bundle",
    )

    positions = [
        release.index(step)
        for step in ordered_steps
    ]

    assert positions == sorted(positions)
