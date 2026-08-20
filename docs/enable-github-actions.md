# Activating the GitHub Actions templates

The repository contains tested workflow templates in [`docs/github-workflows/`](github-workflows/). They are stored as documentation templates rather than active workflow files only because the access token used for the initial automated publication did not have GitHub’s separate `workflows` permission. This constraint does **not** affect the source, tests, Windows build scripts, or installer configuration.

To activate CI after cloning the repository, copy the templates into GitHub’s active workflow directory and commit them with a token or browser session that has permission to update workflow files:

```bash
mkdir -p .github/workflows
cp docs/github-workflows/ci.yml .github/workflows/ci.yml
cp docs/github-workflows/windows-package.yml .github/workflows/windows-package.yml
git add .github/workflows
git commit -m "ci: activate quality and Windows package workflows"
git push
```

| Template | Trigger | Outcome |
| --- | --- | --- |
| `ci.yml` | Pushes and pull requests to `main` | Runs backend lint/tests and frontend lint/production build. |
| `windows-package.yml` | Manual trigger or `v*` tag | Builds the Python sidecar and NSIS x64 installer on `windows-latest`, then uploads the `.exe` as an artifact. |

> The Windows workflow is deliberately kept intact and ready to activate. It is not represented as active in this published revision because doing so would have caused the entire initial push to be rejected.
