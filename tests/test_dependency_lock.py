"""Guard that Pipfile.lock actually covers the Pipfile.

Found 2026-09-10: the committed lock was missing five declared packages
(whitenoise and the four opentelemetry ones). CI never noticed because
`pipenv install --dev` silently re-locks when the lock is out of date —
every run resolved dependencies afresh and installed what the Pipfile
asked for, so the broken lock was invisible:

    Pipfile.lock (3194b386...) out of date: run `pipenv lock` to update
    Locking dependencies...
    Updated Pipfile.lock

Two consequences. The build was not reproducible — any breaking transitive
release could have failed CI with no code change. And the moment the lock
hash matched again, `pipenv install` stopped re-locking and installed
strictly from the lock, so 161 tests failed on ModuleNotFoundError.

`pipenv verify` only compares the Pipfile hash, which was green while
packages were missing. This checks the thing that actually matters.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPFILE = REPO_ROOT / 'Pipfile'
PIPFILE_LOCK = REPO_ROOT / 'Pipfile.lock'
REQUIREMENTS = REPO_ROOT / 'requirements.txt'

SECTIONS = (('packages', 'default'), ('dev-packages', 'develop'))

# Declared in [packages] but legitimately absent from requirements.txt: this is
# tooling for the *test suite*, not something the running app imports. pyyaml
# only backs tests/test_deploy_config.py's parsing of cloudbuild.yaml/ci.yml —
# it is correctly declared under [dev-packages] too; the [packages] copy is a
# pre-existing duplication from the commit that added it (`git log -p --
# Pipfile`) and is out of scope for this guard.
NOT_SHIPPED = {'pyyaml'}


def _normalise(name):
    return name.lower().replace('_', '-')


def declared_packages(section):
    match = re.search(rf'\[{section}\](.*?)(\n\[|\Z)', PIPFILE.read_text(), re.S)
    if not match:
        return []
    return [_normalise(n) for n in re.findall(r'^([A-Za-z0-9_.-]+)\s*=', match.group(1), re.M)]


def locked_packages(key):
    lock = json.loads(PIPFILE_LOCK.read_text())
    return {_normalise(name) for name in lock[key]}


def shipped_packages():
    """Package names in requirements.txt — what Dockerfile.cloudrun actually
    installs. Version pins, extras and markers are stripped; only presence is
    compared, since requirements.txt's pins are a separate `pip freeze`
    snapshot that legitimately drifts from Pipfile.lock's own pins."""
    names = []
    for line in REQUIREMENTS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name = re.split(r'[=<>!~\[;]', line, maxsplit=1)[0].strip()
        if name:
            names.append(_normalise(name))
    return names


@pytest.mark.unit
@pytest.mark.parametrize(('section', 'lock_key'), SECTIONS)
def test_every_declared_package_is_in_the_lock(section, lock_key):
    declared = declared_packages(section)
    locked = locked_packages(lock_key)

    assert declared, f'expected packages declared under [{section}]'
    missing = sorted(p for p in declared if p not in locked)
    assert not missing, (
        f'{len(missing)} package(s) declared in [{section}] but absent from '
        f'Pipfile.lock: {missing}. Run `pipenv lock` and commit the result — '
        f'`pipenv install <pkg>` can update the hash without fully re-resolving.'
    )


@pytest.mark.unit
def test_every_shipped_package_is_in_requirements_txt():
    """Guard that requirements.txt actually covers Pipfile's [packages].

    Found 2026-09-24: `google-genai` was added to Pipfile/Pipfile.lock for the
    in-app assistant, and all 419 tests passed — CI installs with pipenv, so
    the SDK was always present there. But production does not use pipenv:
    `.github/workflows/deploy.yml` -> `cloudbuild.yaml` ->
    `Dockerfile.cloudrun` does `COPY requirements.txt` then
    `pip install -r requirements.txt`, and nothing anywhere runs `pipenv
    requirements` to regenerate that file from the Pipfile. The deployed
    container had no SDK, so the first real assistant turn would have raised
    ImportError — invisible until rollout, because the test suite never
    looked at the file that actually ships.

    This compares presence only, not versions: requirements.txt is a pinned
    `pip freeze` snapshot that is allowed to drift from Pipfile.lock's own
    pins (that is how `openai` sat at 1.41.0 in requirements.txt while the
    lock had already moved to 3.19.2, before openai was removed entirely).
    Presence is what would have caught this incident.
    """
    declared = [p for p in declared_packages('packages') if p not in NOT_SHIPPED]
    shipped = set(shipped_packages())

    assert declared, 'expected packages declared under [packages]'
    missing = sorted(p for p in declared if p not in shipped)
    assert not missing, (
        f'{len(missing)} package(s) declared in Pipfile [packages] but absent from '
        f'requirements.txt, which is what Dockerfile.cloudrun actually installs: '
        f'{missing}. Add them to requirements.txt with a pinned version.'
    )


@pytest.mark.unit
def test_ci_installs_strictly_from_the_lock():
    """--deploy makes an out-of-date lock a hard failure instead of a silent
    re-lock. Without it the guard above is unenforceable in CI, because CI
    would regenerate the lock before the tests ever read it."""
    ci = (REPO_ROOT / '.github' / 'workflows' / 'ci.yml').read_text()

    assert '--deploy' in ci, 'CI must install with --deploy so it cannot silently re-lock'
