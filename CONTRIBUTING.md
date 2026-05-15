# Contributing

Thanks for your interest in IDP Platform.

## Getting Started

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Install dependencies: `pip install -r requirements.txt`
4. Run tests: `python -m unittest tests.test_idp -v`

## Code Style

- Follow PEP 8 — enforced via Ruff (`ruff check .`)
- Keep hexagonal architecture boundaries clean
- Domain models must have zero framework dependencies
- Use type hints everywhere

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `chore:` maintenance
- `test:` tests
- `ci:` CI/CD

## PR Checklist

- [ ] Tests pass
- [ ] Ruff lint passes
- [ ] No secrets or tokens committed
- [ ] Public methods have docstrings
