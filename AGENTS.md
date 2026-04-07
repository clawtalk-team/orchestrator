# AGENTS.md

This file defines the workflow rules for all developer agents working in this repository.

---

## Workflow

1. Review the ticket — if there are any questions, ask them on the ticket or to the requestor before starting. Do not start work with unresolved ambiguity.
2. Map out your approach briefly (comment on the ticket or in the PR description). This is not a blocking step — proceed after noting your plan.
3. Work must be done in small, focused chunks on a dedicated feature branch. Do not work on main. Look to push to github and get a PR raised and review done before the change gets too big.
4. You must write and/or update unit tests for any code that is written — for new code define what success looks like before implementing.
5. Implement the change and run the tests to confirm completion.
6. There must be tests for linting
7. There must be tests for code coverage
8. There must be tests for integration, these must run in a local stubbed mode and also have an option to test against real endpoints
9. Run all the check commands from the Makefile before pushing — must pass before pushing.
10. Code coverage by test must not decrease on any merge
11. Push the branch and open a PR.
12. Wait for Gemini code review — address **all** comments before merging.
13. When CI is green and all comments addressed, merge the PR.
14. Update README.md, AGENTS.md, and any other relevant docs as part of the PR.

---

## Branching & PRs

- **Never commit directly to main/master** — always use a feature branch
- Branch naming: `feature/issue-{N}-{description}` or `fix/issue-{N}-{description}`
- **One issue per PR** — keep PRs focused
- **Squash merge** PRs, delete the branch after merge
- PR title: `feat|fix|chore|docs(#N): Brief description` — e.g. `feat(#12): add user login endpoint`
- PR body must include: what changed, how to test it, `Closes #N`

---

## Before Pushing — Required Checks

Run all of the following before pushing any branch. **No exceptions.**

```bash
# Linting — must be clean
make lint

# Unit tests — must be 100% green
make test

# Integration tests — must be 100% green (REQUIRED)
make test-integration

# Full CI check (recommended)
make ci
```

- Tests must pass. If a test fails, fix the code — never skip or comment out the test.
- If you break a test, that is a bug. Stop and fix it before continuing.
- Never ever send me something to test unless you have actually tested it first this includes simple one liners you have concocted from your memory
- **Integration tests must pass before pushing** — these test the full stack including OpenClaw, auth-gateway, and voice-gateway integration.
- **Test coverage must not decrease.**

---

## Code Review

PRs are reviewed by a different model to the one that wrote the code:

| Author | Reviewer |
|---|---|
| Claude (any) | Gemini |
| Gemini | Claude |
| Codex / GPT | Claude or Gemini |

**Address ALL review comments before merging** — not just critical severity. Medium and low comments require a response. You may decline a comment with a clear reason, but you cannot silently ignore it.

---

## Testing Standards

- Write tests first where possible (TDD)
- Every bug fix must include a regression test that would have caught the bug
- Every new feature must have tests covering the happy path and key edge cases
- Do not write tests that pass without asserting meaningful behaviour
- Test coverage must not decrease across the PR

---

## Codex Review (Required)

Run Codex review on your branch before opening a PR:

```bash
codex "Review the changes I've made in this branch for bugs, edge cases, security issues, and code quality."
```

This is not optional. If Codex flags something you disagree with, note your reasoning in the PR body.

---

## Architecture Notes (from PoC)

- Agent authenticates with hub via device auth flow on startup
- Hub issues JWT; agent uses it to pull config (LiveKit/Deepgram/OpenAI keys) and register
- Hub dispatches agent to LiveKit rooms when callers connect via `/connect`
- `session.start()` handles LiveKit connection internally — do not add `ctx.connect()` before it
- Agent token + ID persisted in `.hub-token-*` and `.hub-agent-id-*` files

### Known PoC lesson
- The hub migration introduced explicit agent dispatch (`/connect` now calls LiveKit API to dispatch)
- Adding `ctx.connect()` before `session.start()` interferes with audio track subscription in livekit-agents 1.x
- **Lesson:** changing agent startup code requires a full end-to-end test before merging

---

## Background Tasks

Any time you kick off a background task (deploy, test run, agent spawn), immediately schedule a follow-up reminder so it doesn't get lost if the session ends. Report back when done — don't leave things hanging.

---

## Repository Scope

This agent is responsible for the following repositories:
- `clawtalk-team/orchestrator` — Python orchestrator service for managing containerized agents

### External Dependencies

**OpenClaw Repository** (Read-Only Reference):
- **GitHub**: https://github.com/clappclaw/openclaw
- **Local Copy**: `~/Documents/workspace/openclaw`
- **Purpose**: Core OpenClaw agent framework — you must be an expert on OpenClaw internals and how openclaw-agent interfaces with it
- **Key Components**:
  - Agent configuration schema (`types.agents.ts`, `zod-schema.core.ts`)
  - System prompt generation (`agents/system-prompt.ts`)
  - Skills loading and management (`skills/workspace.ts`)
  - Session-to-agent resolution (`agent-scope.ts`)
  - Gateway API methods (`gateway/server-methods/agents.ts`, `skills.ts`)
  - SOUL.md/IDENTITY.md templating (`docs/reference/templates/`)

**Note**: This is an external repository. Do NOT make changes to it. Refer to it for understanding OpenClaw's agent configuration API, system prompt structure, and skill management.

### Responsibilities
- Write, test, and maintain code in assigned repositories
- Keep documentation up to date (README, AGENTS.md, API docs)
- **Maintain this AGENTS.md file** — update workflow rules, testing standards, and architecture notes as the project evolves
- Understand OpenClaw internals to ensure proper integration with openclaw-agent

### Cross-Repository Work — PROHIBITED

**You MUST NOT make changes to any repository outside your assigned scope without explicit permission.**

- Do NOT modify files in other repositories (e.g., `auth-gateway`, `voice-gateway`, `e2e`, `architecture`)
- Do NOT commit changes to other repositories
- Do NOT create PRs in other repositories
- Do NOT run commands that modify files outside `openclaw-agent`

**If you need changes in another repository:**
1. STOP immediately
2. Document what changes are needed and why
3. Contact your manager or the agent responsible for that repository
4. Wait for explicit approval before proceeding

**Exception:** Reading files from other repositories for context is permitted.

If asked to work in a repository not on this list, escalate to your manager before proceeding.

**Note:** Developer agents are assigned no more than 2 repos as a rule, 3 at an absolute maximum and only if the third is small and infrequent.

---

## Pre-commit Checklist

- [ ] All tests pass (`make test`)
- [ ] Integration tests pass (`make test-integration`)
- [ ] No linting errors (`make lint`)
- [ ] No debug print statements or console.logs
- [ ] No hardcoded secrets or credentials
- [ ] Commit message follows convention (`feat:`, `fix:`, `chore:`)
- [ ] Codex review run and issues addressed
- [ ] README and docs updated if behaviour changed

---

## Escalation

If you are stuck on the same problem for more than one iteration, stop and contact your manager. Do not continue looping. Your manager will either unblock you, re-scope the task, or bring in outside help.
