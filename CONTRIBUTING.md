# Contributing to orchestrator

Thanks for your interest in contributing. This document covers how to get the
project running locally, what we expect from a change, and how review works.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
Security problems go through [SECURITY.md](SECURITY.md), **not** the issue
tracker.

## Getting set up

You will need Python 3.11 and Docker (the integration tests run against a
local DynamoDB container).

```bash
make install-dev     # creates a venv and installs runtime + dev dependencies
cp .env.example .env # then fill in the values you need
```

## Making a change

Work on a feature branch — never directly on `main`.

```
feature/issue-{N}-{short-description}
fix/issue-{N}-{short-description}
```

Keep pull requests focused: one issue per PR. A large PR that does several
unrelated things will be sent back to be split up.

### Tests are not optional

- New code needs tests. Decide what success looks like before you implement.
- Every bug fix needs a regression test — one that fails before your fix and
  passes after.
- Cover the happy path and the edge cases that matter (empty input, error
  paths, concurrent access).
- A test that passes without asserting meaningful behaviour is worse than no
  test.
- **Never skip, delete, or comment out a failing test to get CI green.** If a
  test fails, that is a bug — fix the code.
- Coverage must not decrease.

### Before you push

All of these must pass:

```bash
make lint             # black, isort, flake8
make test             # unit tests
make test-integration # full stack; starts DynamoDB Local via docker compose
make ci               # all of the above
```

Do not ask anyone to test something you have not run yourself first.

## Opening a pull request

PR title follows conventional commits:

```
feat(#12): add user login endpoint
fix(#34): handle empty config payload
docs(#56): clarify deployment prerequisites
```

The body should say what changed, how to test it, and close the issue with
`Closes #N`.

Update `README.md` and anything in `docs/` that your change makes stale, as
part of the same PR.

## Review

Every PR gets an automated cross-model review — code written by one model is
reviewed by a different one — alongside human review. This runs automatically
on branches in this repository; on pull requests from forks it is skipped,
because forked workflows have no access to the API credentials it needs. A
maintainer will review those by hand.

Address **all** review comments before merging, not just the ones marked
critical. You may decline a suggestion with a clear reason — that is a normal
part of review — but please don't leave comments unanswered.

We squash-merge and delete the branch afterwards.

## Licence

By contributing, you agree that your contributions will be licensed under the
[MIT Licence](LICENSE) that covers this project.
