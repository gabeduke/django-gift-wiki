"""Guards for the deploy race in issue #85.

On 2026-07-22 two PR deploys started 45s apart. `cloudbuild.yaml` pushed an
untagged image (implicit `:latest`) and then deployed that mutable tag, so the
second build's deploy step resolved to the *first* build's digest: dev served
PR #82's code while PR #83's checks were green and it had "deployed last".

Both halves of the fix are config, which is exactly the kind of thing that gets
quietly reverted during an unrelated edit. These tests are the guard.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDBUILD = REPO_ROOT / 'cloudbuild.yaml'
CI_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'ci.yml'
PROD_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'deploy.yml'

# Every reference to the service image, with whatever tag follows it.
IMAGE_REF = re.compile(r'gcr\.io/\$PROJECT_ID/\$\{_SERVICE_NAME\}(:[^\s\'"\\]*)?')


@pytest.mark.unit
class TestImmutableImageTags:
    def test_no_service_image_is_referenced_without_a_tag(self):
        """An untagged reference resolves :latest at deploy time, which is the
        race itself: whichever concurrent build pushed last wins."""
        refs = IMAGE_REF.findall(CLOUDBUILD.read_text())

        assert refs, 'expected the service image to be referenced in cloudbuild.yaml'
        untagged = [r for r in refs if not r]
        assert not untagged, f'{len(untagged)} untagged service image reference(s) in cloudbuild.yaml'

    def test_every_tag_is_the_per_commit_sha(self):
        """`:latest` is mutable; only a per-commit tag is safe to deploy."""
        refs = [r for r in IMAGE_REF.findall(CLOUDBUILD.read_text()) if r]

        mutable = [r for r in refs if '_GIT_SHA' not in r]
        assert not mutable, f'mutable image tag(s) still referenced: {mutable}'

    def test_git_sha_substitution_is_declared(self):
        config = yaml.safe_load(CLOUDBUILD.read_text())

        assert '_GIT_SHA' in config.get('substitutions', {})

    def test_ci_passes_the_commit_sha_to_cloud_build(self):
        assert '_GIT_SHA=' in CI_WORKFLOW.read_text()


@pytest.mark.unit
class TestSerializedDeploys:
    def test_deploy_dev_runs_one_at_a_time(self):
        """Tagging alone stops the wrong image deploying, but concurrent runs
        still race `terraform apply` on the dev state lock (Error 412)."""
        config = yaml.safe_load(CI_WORKFLOW.read_text())
        concurrency = config['jobs']['deploy-dev'].get('concurrency')

        assert concurrency, 'deploy-dev needs a concurrency group'
        assert concurrency['group'] == 'deploy-dev'

    def test_queued_deploys_are_not_cancelled(self):
        """Cancelling would leave dev running whatever deployed last by luck —
        the same class of bug. Each queued deploy must complete in order."""
        config = yaml.safe_load(CI_WORKFLOW.read_text())

        assert config['jobs']['deploy-dev']['concurrency']['cancel-in-progress'] is False

    def test_terraform_apply_waits_for_the_state_lock(self):
        """Belt and braces for the Error 412 in #85: even serialized, a stale
        lock should be waited on rather than failing the deploy outright."""
        assert '-lock-timeout=' in CI_WORKFLOW.read_text()


@pytest.mark.unit
class TestProductionDeploy:
    """Production submits the same cloudbuild.yaml, so it inherits the same
    race. It is less concurrent than dev, not immune: two merges landing close
    together is exactly the December pattern.
    """

    def test_prod_passes_the_commit_sha_to_cloud_build(self):
        assert '_GIT_SHA=' in PROD_WORKFLOW.read_text()

    def test_prod_deploys_run_one_at_a_time(self):
        config = yaml.safe_load(PROD_WORKFLOW.read_text())
        concurrency = config['jobs']['deploy'].get('concurrency')

        assert concurrency, 'prod deploy needs a concurrency group'
        assert concurrency['cancel-in-progress'] is False

    def test_prod_terraform_apply_waits_for_the_state_lock(self):
        assert '-lock-timeout=' in PROD_WORKFLOW.read_text()
