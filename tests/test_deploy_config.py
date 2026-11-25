"""Guards for deploy config that is easy to drop in an unrelated edit.

The deploy race in issue #85: on 2026-07-22 two PR deploys started 45s apart.
`cloudbuild.yaml` pushed an untagged image (implicit `:latest`) and then
deployed that mutable tag, so the second build's deploy step resolved to the
*first* build's digest: dev served PR #82's code while PR #83's checks were
green and it had "deployed last".

Upload storage: Django 5.1 removed DEFAULT_FILE_STORAGE and ignores it
silently, so prod wrote every upload to the container's disk, where it was
never served and was lost on redeploy. Media storage must come from STORAGES.

HTTPS hardening in issue #131: with DEBUG off (dev and prod Cloud Run), Django
trusts Cloud Run's X-Forwarded-Proto, marks its own cookies Secure and sends
HSTS. Local `make run` (DEBUG on, plain HTTP) must keep Django's defaults.

All of it is config, which is exactly the kind of thing that gets quietly
reverted during an unrelated edit. These tests are the guard.
"""

import importlib.util
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from django.core.checks import Tags, run_checks
from django.test import Client, override_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDBUILD = REPO_ROOT / 'cloudbuild.yaml'
CI_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'ci.yml'
PROD_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'deploy.yml'
SETTINGS_FILE = REPO_ROOT / 'giftwiki' / 'settings.py'

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


# ---- HTTPS hardening (#131) -------------------------------------------------

HARDENING = (
    'SECURE_PROXY_SSL_HEADER',
    'SESSION_COOKIE_SECURE',
    'CSRF_COOKIE_SECURE',
    'SECURE_HSTS_SECONDS',
)
# What a request through Cloud Run's front end looks like to the container: the
# browser's Host passed through, and the scheme it used. The test client sends
# no Host by default, and Django would then build one from SERVER_PORT 80
# ("testserver:80"), which no https:// Origin or Referer could ever match.
VIA_CLOUD_RUN = {'Host': 'testserver', 'X-Forwarded-Proto': 'https'}
# An unmasked CSRF secret; Django accepts it as both cookie and token.
CSRF_SECRET = 'a' * 32


def load_settings(monkeypatch, *, debug):
    """Evaluate giftwiki/settings.py afresh with DJANGO_DEBUG set as given.

    The result is a private module object: neither sys.modules nor
    django.conf.settings changes, so the rest of the suite keeps the settings
    it started with, whatever DJANGO_DEBUG the process happens to have.
    """
    monkeypatch.setenv('DJANGO_DEBUG', 'True' if debug else 'False')
    # Would build a Cloud Logging client on import.
    monkeypatch.delenv('DJANGO_ENVIRONMENT', raising=False)
    spec = importlib.util.spec_from_file_location('giftwiki._settings_under_test', SETTINGS_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def deployed(monkeypatch):
    """Settings as dev and prod Cloud Run get them: neither sets DJANGO_DEBUG."""
    return load_settings(monkeypatch, debug=False)


@pytest.fixture
def local_dev(monkeypatch):
    """Settings for `make run` over plain HTTP."""
    return load_settings(monkeypatch, debug=True)


@pytest.fixture
def as_deployed(settings, deployed):
    """Apply the deployed values to this test's requests."""
    for name in HARDENING:
        setattr(settings, name, getattr(deployed, name))
    return settings


@pytest.mark.unit
class TestHttpsHardeningSettings:
    def test_django_trusts_the_scheme_cloud_run_forwards(self, deployed):
        """Cloud Run ends TLS in front of the container, so without this every
        request looks like plain HTTP to Django."""
        assert deployed.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https')

    def test_session_and_csrf_cookies_are_https_only(self, deployed):
        assert deployed.SESSION_COOKIE_SECURE is True
        assert deployed.CSRF_COOKIE_SECURE is True

    def test_hsts_is_on(self, deployed):
        """An hour while it rolls out. Raising it to a year is the plan;
        dropping or shortening it is not."""
        assert deployed.SECURE_HSTS_SECONDS >= 3600

    @pytest.mark.parametrize(
        'name', ['SECURE_SSL_REDIRECT', 'SECURE_HSTS_INCLUDE_SUBDOMAINS', 'SECURE_HSTS_PRELOAD']
    )
    def test_nothing_hard_to_walk_back_is_switched_on(self, deployed, name):
        """#131 leaves these off on purpose. Turning one on is a decision of
        its own: make it deliberately and update this test."""
        assert not getattr(deployed, name, False)

    @pytest.mark.parametrize('name', HARDENING)
    def test_local_http_dev_keeps_djangos_defaults(self, local_dev, name):
        """A Secure cookie set over plain http:// may never come back."""
        assert not hasattr(local_dev, name)

    def test_the_deploy_check_no_longer_flags_them(self, deployed):
        """What `manage.py check --deploy` reports for the deployed values."""
        values = {name: getattr(deployed, name) for name in HARDENING}
        with override_settings(DEBUG=False, **values):
            flagged = {
                message.id
                for message in run_checks(include_deployment_checks=True, tags=[Tags.security])
            }

        assert not flagged & {'security.W004', 'security.W012', 'security.W016'}


@pytest.fixture
def with_s3(monkeypatch):
    """Settings as Cloud Run gets them: USE_S3=TRUE and a bucket (terraform/main.tf)."""
    monkeypatch.setenv('USE_S3', 'TRUE')
    monkeypatch.setenv('AWS_STORAGE_BUCKET_NAME', 'gift-wiki')
    return load_settings(monkeypatch, debug=False)


@pytest.fixture
def without_s3(monkeypatch):
    monkeypatch.delenv('USE_S3', raising=False)
    return load_settings(monkeypatch, debug=True)


@pytest.mark.unit
class TestUploadStorage:
    def test_uploads_go_to_s3_when_use_s3(self, with_s3):
        """What Django actually builds from the settings, not just a string."""
        from django.core.files.storage import StorageHandler
        from storages.backends.s3boto3 import S3Boto3Storage

        storage = StorageHandler(with_s3.STORAGES)['default']

        assert isinstance(storage, S3Boto3Storage)

    def test_s3_settings_reach_the_storage(self, with_s3):
        """The bucket from the environment, and writing names as given: every
        upload name is random, and checking first needs s3:ListBucket."""
        from django.core.files.storage import StorageHandler

        aws = {name: getattr(with_s3, name) for name in dir(with_s3) if name.startswith('AWS_')}
        with override_settings(**aws):
            storage = StorageHandler(with_s3.STORAGES)['default']

        assert storage.bucket_name == 'gift-wiki'
        assert storage.file_overwrite is True
        # The custom domain makes every URL unsigned and public
        assert storage.url('wishlist_images/a.jpg') == (
            'https://gift-wiki.s3.amazonaws.com/wishlist_images/a.jpg'
        )

    def test_saving_to_s3_never_asks_whether_a_name_is_taken(self, with_s3):
        """Prod's key can't HeadObject a missing key (403, not 404), so the
        "is it taken?" check 500'd every cover photo upload."""
        from django.core.files.storage import StorageHandler

        aws = {name: getattr(with_s3, name) for name in dir(with_s3) if name.startswith('AWS_')}
        with override_settings(**aws):
            storage = StorageHandler(with_s3.STORAGES)['default']
            with patch.object(storage, 'exists', side_effect=AssertionError('HeadObject')):
                name = storage.get_available_name('wishlist_images/a.jpg')

        assert name == 'wishlist_images/a.jpg'

    @pytest.mark.parametrize(
        'model,field', [('WikiUser', 'profile_picture'), ('WikiUser', 'profile_picture_web'),
                        ('WikiUser', 'profile_picture_thumbnail'), ('WishList', 'image'),
                        ('Family', 'image'), ('Suggestion', 'image'), ('ExchangeLetter', 'image')],
    )
    def test_every_upload_gets_a_random_name(self, model, field):
        """With overwriting on, a reused name would replace someone else's photo."""
        from gift import models

        upload_to = models.__dict__[model]._meta.get_field(field).upload_to

        first, second = upload_to(None, 'photo.jpg'), upload_to(None, 'photo.jpg')
        assert first != second
        assert 'photo' not in first

    def test_uploads_stay_on_local_disk_without_s3(self, without_s3):
        from django.core.files.storage import FileSystemStorage, StorageHandler

        storage = StorageHandler(without_s3.STORAGES)['default']

        assert type(storage) is FileSystemStorage

    @pytest.mark.parametrize('fixture', ['with_s3', 'without_s3'])
    def test_static_urls_stay_unfingerprinted(self, fixture, request):
        """The app relies on plain static URLs plus {% vstatic %} (gift/pwa.py)."""
        module = request.getfixturevalue(fixture)

        assert module.STORAGES['staticfiles']['BACKEND'] == (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
        )

    @pytest.mark.parametrize('name', ['DEFAULT_FILE_STORAGE', 'STATICFILES_STORAGE'])
    def test_no_removed_storage_setting_is_used(self, with_s3, name):
        """Both were removed in Django 5.1 and are ignored without a word."""
        assert not hasattr(with_s3, name)


def sign_in(client, **kwargs):
    """POST /sessionLogin with a verified token the Firebase SDK accepts."""
    firebase = MagicMock()
    firebase.verify_id_token.return_value = {
        'email': 'ellie@gmail.com',
        'email_verified': True,
        'firebase': {'sign_in_provider': 'google.com'},
        'auth_time': 0,
        'iat': 0,
    }
    firebase.create_session_cookie.return_value = 'minted-cookie'
    with (
        patch('gift.middleware.firebase_auth._get_firebase_auth', return_value=firebase),
        patch('time.time', return_value=1),
    ):
        return client.post(
            '/sessionLogin', data='{"idToken": "abc"}', content_type='application/json', **kwargs
        )


def csrf_client(user):
    """A client that enforces CSRF like a browser would meet it."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    client.cookies['csrftoken'] = CSRF_SECRET
    return client


@pytest.mark.api
class TestDeployedRequests:
    """The deployed values applied to real requests: what a browser gets
    through Cloud Run, and that plain HTTP (local runserver, anything reaching
    the container without the forwarded header) is not changed."""

    def test_hsts_is_sent_over_https(self, as_deployed, client):
        hsts = client.get('/robots.txt', headers=VIA_CLOUD_RUN)['Strict-Transport-Security']

        assert hsts.startswith('max-age=')
        assert 'includeSubDomains' not in hsts
        assert 'preload' not in hsts

    def test_plain_http_is_never_pinned_to_https(self, as_deployed, client):
        assert 'Strict-Transport-Security' not in client.get('/robots.txt')

    def test_health_still_answers_plain_http(self, as_deployed, client):
        """No redirect: probes reach the container without the forwarded header."""
        assert client.get('/health/').status_code == 200

    def test_firebase_cookie_is_secure_through_cloud_run(self, as_deployed, client, db):
        response = sign_in(client, headers=VIA_CLOUD_RUN)

        assert response.status_code == 200
        assert response.cookies['__session']['secure']

    def test_firebase_cookie_still_works_over_plain_http(self, as_deployed, client, db):
        response = sign_in(client)

        assert response.status_code == 200
        assert not response.cookies['__session']['secure']

    def test_djangos_session_cookie_is_secure(self, as_deployed, client, user):
        client.force_login(user)

        response = client.post('/over-the-shoulder/', {'on': '1'}, headers=VIA_CLOUD_RUN)

        assert response.cookies['sessionid']['secure']

    def test_a_browser_post_passes_the_csrf_origin_check(self, as_deployed, user):
        """With the scheme trusted, Django accepts Origin https://<host> by
        itself; before, that passed only if CSRF_TRUSTED_ORIGINS listed it.
        `testserver` is not in CSRF_TRUSTED_ORIGINS here."""
        response = csrf_client(user).post(
            '/over-the-shoulder/',
            {'on': '1'},
            headers={**VIA_CLOUD_RUN, 'Origin': 'https://testserver', 'X-CSRFToken': CSRF_SECRET},
        )

        assert response.status_code == 302

    def test_a_post_without_origin_passes_the_referer_check(self, as_deployed, user):
        """No Origin on HTTPS means Django checks Referer strictly. Django's
        default Referrer-Policy (same-origin) keeps it on our own POSTs."""
        response = csrf_client(user).post(
            '/over-the-shoulder/',
            {'on': '1'},
            headers={
                **VIA_CLOUD_RUN,
                'Referer': 'https://testserver/wishlist/1/',
                'X-CSRFToken': CSRF_SECRET,
            },
        )

        assert response.status_code == 302

    def test_a_cross_site_post_is_still_refused(self, as_deployed, user):
        response = csrf_client(user).post(
            '/over-the-shoulder/',
            {'on': '1'},
            headers={
                **VIA_CLOUD_RUN,
                'Origin': 'https://evil.example.com',
                'X-CSRFToken': CSRF_SECRET,
            },
        )

        assert response.status_code == 403
