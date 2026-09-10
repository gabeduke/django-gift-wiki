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

SECTIONS = (('packages', 'default'), ('dev-packages', 'develop'))


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
def test_ci_installs_strictly_from_the_lock():
    """--deploy makes an out-of-date lock a hard failure instead of a silent
    re-lock. Without it the guard above is unenforceable in CI, because CI
    would regenerate the lock before the tests ever read it."""
    ci = (REPO_ROOT / '.github' / 'workflows' / 'ci.yml').read_text()

    assert '--deploy' in ci, 'CI must install with --deploy so it cannot silently re-lock'
