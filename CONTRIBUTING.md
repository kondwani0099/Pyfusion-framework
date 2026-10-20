# Contributing to PyFusion

Thanks for your interest in improving PyFusion! This guide explains how to get set up and what we expect
from contributions.

## Development setup

```bash
git clone https://github.com/kondwani0099/pyfusion-framework.git
cd pyfusion-framework
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Run the demo app with hot reload:

```bash
pyfusion run web --open
```

## Before opening a pull request

```bash
ruff check .                 # lint
pytest --cov=fusionlib       # tests
bandit -r fusionlib -lll     # high-severity security findings
```

All three run in CI on Python 3.10–3.13 for Linux, macOS and Windows.

## Guidelines

- **Open an issue first** for new features or breaking changes so the design can be discussed.
- **Add tests** for every bug fix and feature (`tests/`). Security-relevant code needs negative tests,
  e.g. "tampered snapshot is rejected".
- **Keep the public API stable.** Anything exported from `fusionlib/__init__.py` is public. Deprecate
  before removing.
- **Update `CHANGELOG.md`** under `## [Unreleased]`.
- **Use small, focused commits.** [Conventional Commits](https://www.conventionalcommits.org/) are
  preferred (`feat:`, `fix:`, `docs:`, `security:`).
- **Never weaken a security default** (CSRF, state signing, CSP, hashing policy) without a linked
  discussion.

## Reporting security issues

Do **not** open a public issue. See [SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating you agree to
uphold it.
