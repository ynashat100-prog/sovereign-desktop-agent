# Contributing to Sovereign Desktop Agent

Thank you for contributing. This project treats **security, local-first privacy, and reliability** as higher priorities than feature breadth or cloud convenience.

## Before opening a pull request

Create a focused branch, explain the user-facing motivation, and avoid mixing unrelated refactors with behavioral changes. Any change that introduces a new tool, provider, data store, or permission must include tests and a short threat assessment in the pull request description.

| Check | Command |
| --- | --- |
| Backend lint | `cd backend && ruff check app tests` |
| Backend tests | `cd backend && pytest -q` |
| Frontend production build | `cd frontend && pnpm build` |
| Windows package | Run the `windows-package.yml` workflow or build on Windows as documented in the README. |

## Security requirements

Never commit API keys, credentials, `.env` files, model weights, user conversations, screenshots, database contents, installers, virtual environments, or `node_modules`. Do not add generic shell execution, delete functionality, registry changes, elevation, or network exfiltration through an agent tool without an explicit design review.

The AI model may suggest an action, but it must not decide permission level, invoke operating-system commands directly, or bypass the allow-list. A new tool must declare a deterministic safety tier and include a test covering the denied path.

## Provider changes

Custom-provider metadata may be stored without secrets. API keys must use the operating system credential store and must never appear in logs, traces, API responses, screenshots, or tests. Cloud processing must remain off by default and require a named provider plus an explicit consent signal per request.

## Style and documentation

Use TypeScript for the UI and typed Python for the runtime. Keep UI strings in the localization dictionary and retain Arabic-first RTL behavior. Document any limitation honestly; do not use placeholders or mocks to claim that an unavailable system feature is implemented.
