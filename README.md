# Sovereign Desktop Agent

> **A sovereign-first hybrid desktop AI agent for Windows.** Local execution is the default whenever practical; cloud providers are opt-in, explicitly selected fallbacks.

Sovereign Desktop Agent is a Windows sidebar that combines a Tauri/React interface with a managed FastAPI runtime. It is designed for users who want a practical local assistant without having to manually start Python, Node.js, Rust, or a backend server after installation. Ollama is the preferred local inference engine, while cloud providers remain optional and are governed by an explicit consent boundary.

![Arabic-first first-run experience](assets/ui-preview.webp)

## Product principles

| Principle | How the application enforces it |
| --- | --- |
| **Security first** | The model requests an allow-listed tool; the permission engine, not the model, assigns the safety tier and authorizes execution. |
| **Local-first privacy** | The default mode is **Local Only**. It does not route text, files, or screenshots to any cloud provider. |
| **Explicit cloud consent** | Hybrid mode requires the user to select a provider and approve a clear, per-request disclosure naming the provider and model. |
| **Graceful degradation** | Missing Ollama, models, vision, cloud keys, or memory leave the chat UI, setup wizard, trace viewer, and Demo Mode available. |
| **Usable distribution** | The intended release artifact is a Windows x64 NSIS `.exe` that starts its packaged Python sidecar automatically. |

## Features

The application provides an Arabic-first, RTL/LTR React sidebar with a light and dark theme, a real WebSocket process trace, a first-run setup wizard, an emergency stop control, and a local Demo Mode. The local-model page discovers installed Ollama models, recommends `qwen2.5-coder:7b` and `qwen2.5-coder:14b`, accepts any valid Ollama model name, and invokes the local Ollama pull API only after a confirmation.

| Area | Implemented capability |
| --- | --- |
| **Inference** | Ollama discovery and local generation, Qwen recommendations, Demo Mode, and a provider abstraction for NVIDIA NIM, Mistral, Groq, and custom OpenAI-compatible endpoints. |
| **Cloud configuration** | Add, test, select, and delete custom providers using name, HTTPS base URL, model name, and API key. The metadata file never includes API keys. |
| **Credential safety** | API keys are stored through the operating system credential backend; on Windows this is the Windows Credential Manager. The interface shows only a masked suffix after storage. |
| **Runtime** | FastAPI HTTP endpoints, WebSocket trace events, a deterministic router, explicit state machine, and a user-controlled emergency stop. |
| **Tools** | Active process context, safe file search/read, confirmed file/folder creation and opening, confirmed clipboard access, and a dangerous terminal tier disabled by default. |
| **Privacy** | Context collection is separate from vision. Screenshot analysis is on-demand and requires explicit authorization. |
| **Memory** | Optional local LanceDB service with a clear-all method. Screenshots are not stored automatically. |

## Architecture

```text
Tauri + React sidebar
        │ HTTP / WebSocket
        ▼
FastAPI agent runtime
        │
        ├── Smart Router ──► Ollama (default local path)
        │        │
        │        └── Explicit Hybrid selection ──► OpenAI-compatible cloud provider
        │
        ├── State machine + Live Trace
        ├── Permission engine ──► Allow-listed tool executor
        ├── Context collector / on-demand vision
        └── Optional LanceDB local memory
```

The desktop shell launches the runtime as a bundled sidecar. Tauri supports this pattern specifically for external binaries such as Python API servers, and requires a target-triple suffix for the bundled binary.[1] The repository’s Windows build script produces `agent-runtime-x86_64-pc-windows-msvc.exe` for that purpose.

## Install and first run

### End users

Download the `SovereignDesktopAgent_*_x64-setup.exe` artifact from the GitHub release page, run it, and complete the six-step setup wizard. The wizard checks the desktop runtime and Ollama, explains the recommended models, makes cloud setup optional, and introduces the permission policy.

If Ollama is installed and running, select **Qwen2.5-Coder 7B** for lower-end hardware or **Qwen2.5-Coder 14B** for a higher-end local configuration such as an RTX 3060 with 12 GB VRAM. You may instead select an already-installed Ollama model or enter a different model name. When a model is absent, **Download model** asks for confirmation before starting a local pull and reports progress through the live trace.

> **Important:** The installer bundles the agent runtime but does not bundle Ollama or a multi-gigabyte language model. This is intentional: local model choice and download remain under the user’s control.

### Privacy modes

| Mode | What may run | What may leave the computer |
| --- | --- | --- |
| **Local Only** | Ollama, local tools, local context, and local memory when available. | Nothing is sent to a cloud provider. |
| **Hybrid** | Local inference stays preferred. A configured cloud provider can be selected for a request. | Only the selected request text is sent after a dialog identifies the provider and model. Screenshots require a separate opt-in. |
| **Demo Mode** | Sidebar, chat, trace simulation, setup, and settings. | Nothing; no model provider is required. |

## Cloud providers and API keys

The provider panel includes presets for NVIDIA NIM, Mistral, and Groq, while retaining a generic OpenAI-compatible provider form. Supply a provider name, an **HTTPS** base URL, an API key, and a model. A saved API key is never written to `.env`, JSON, SQLite, logs, or Git. Only a non-secret provider record is stored locally, and the key is retrieved from the credential backend on demand.

The backend rejects a cloud invocation unless the request simultaneously uses Hybrid mode, names a provider, and carries the consent flag created by the UI’s disclosure dialog. A model cannot use a cloud tool or bypass the permission engine.

## Tool permissions

| Tier | Examples | Default behavior |
| --- | --- | --- |
| **Safe** | Read a bounded text file, search a selected folder, view limited process metadata. | Executes through the allow-list. |
| **Confirm** | Create a file/folder, open an application or path, read/write clipboard. | Shows a permission request. |
| **Dangerous** | Terminal commands outside a narrow read-only command set. | Disabled in settings by default; never executable merely because a model asks. |

The initial scope intentionally excludes delete operations, registry modifications, administrator escalation, shutdown, and unrestricted shell execution. The **Stop Agent** button cancels active runs, clears pending approval requests, and prevents further execution steps in that run.

## Development setup

The following commands are for contributors only. They are **not** required by a user who installs the Windows release.

```bash
git clone https://github.com/ynashat100-prog/sovereign-desktop-agent.git
cd sovereign-desktop-agent
cp .env.example .env

# Backend
cd backend
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# Bash: source .venv/bin/activate
pip install -e ".[dev]"
python run.py
```

In another terminal, start the React interface:

```bash
cd frontend
pnpm install
pnpm dev
```

For the integrated desktop shell, build the sidecar on the same operating system as the intended target and then launch Tauri:

```bash
# From repository root
python scripts/build_backend.py
cd frontend
pnpm tauri:dev
```

## Tests and checks

Run the backend tests and lint checks before sending changes for review:

```bash
cd backend
ruff check app tests
pytest -q

cd ../frontend
pnpm build
```

The current automated suite covers the router, state-machine transitions, permission behavior, disabled dangerous tools, API health/setup behavior, Demo Mode, and the explicit cloud-consent gate. Ready-to-activate GitHub Actions templates repeat these checks and build the Windows installer on a Windows runner; see [the activation note](docs/enable-github-actions.md).

## Build the Windows x64 NSIS installer

The primary supported release path is Windows 10/11 x64. On a Windows development machine or a Windows CI runner, install the usual Tauri prerequisites, then run:

```powershell
# At repository root
py -m pip install -e ".\backend[dev]"
py .\scripts\build_backend.py
cd .\frontend
pnpm install --frozen-lockfile
pnpm tauri:build
```

The NSIS installer is produced under Tauri’s release bundle directory. Tauri documents NSIS setup executables as a supported Windows distribution format, and notes that a Windows environment or CI is the preferred way to produce Windows builds.[2] This repository therefore provides a Windows GitHub Actions build rather than representing an untested Linux cross-build as a release.

## Repository layout

```text
backend/                 FastAPI agent runtime, models, providers, tools, tests
frontend/                React UI, Tauri shell, capabilities, Windows bundle config
scripts/                 Sidecar and icon build scripts
assets/                  App icon and UI preview
docs/                    Verification, design, and activation notes
docs/github-workflows/   Ready-to-activate CI and Windows packaging templates
```

## Current limitations

This is an MVP foundation, not a claim that every optional integration is present on every device. Vision providers require a separately configured and available vision model; screenshots are intentionally not persisted. Windows active-window metadata is represented by a cross-platform safe fallback in this environment and should be enhanced with a native Windows adapter before relying on precise window-title automation. The development sandbox used for this work runs Linux and does not contain a Windows desktop or Rust toolchain, so the repository verifies backend tests and the frontend production build locally while the Windows installer is designed to be built and validated by the ready-to-activate Windows workflow template. The initial publishing token cannot create workflow files; [activation is documented](docs/enable-github-actions.md).

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Never commit secrets, `.env` files, downloaded model artifacts, virtual environments, `node_modules`, database files, or compiled installers.

## License

This repository is released under the [MIT License](LICENSE).

## References

[1]: https://v2.tauri.app/develop/sidecar/ "Tauri v2: Embedding External Binaries"
[2]: https://v2.tauri.app/distribute/windows-installer/ "Tauri v2: Windows Installer"
