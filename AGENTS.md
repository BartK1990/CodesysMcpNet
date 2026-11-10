# Agent instructions

Instructions for AI coding agents (Claude Code, Codex, OpenCode, ...) working in this repository.
This is the canonical instructions file: put new rules here, not in `CLAUDE.md`.

## What this is

An ASP.NET Core 10 server (Windows only) that drives a CODESYS V3 project through the official
CODESYS Scripting Engine. It exposes the same operations as a REST API and as an MCP server
(Streamable HTTP at `/mcp`), on one Kestrel instance at `http://127.0.0.1:5088`. The settings
page at `/` (`wwwroot/index.html`, a single static file) configures CODESYS.exe, the profile and
the project(s).

## Commands

```bash
dotnet build CodesysMcpServer.Web
dotnet run --project CodesysMcpServer.Web --launch-profile CodesysMcpServer   # http://127.0.0.1:5088, Swagger at /swagger
python CodesysMcpServer.Web/Scripts/selftest.py                               # Python facade/parser tests, no CODESYS needed
cd docs && npm ci && npm run build                                            # docs site; `npm run dev` to preview
```

There is no .NET test project and no linter. `selftest.py` is the only automated test. It runs
every `test_*` function listed in `main()`; to run one, call it from Python, e.g.
`python -c "import sys; sys.path.insert(0, 'CodesysMcpServer.Web/Scripts'); import selftest; selftest.test_libraries()"`.
Anything that touches the real engine can only be checked against an installed CODESYS with a
real project (configure it on the settings page, then call the REST endpoints).

The release version is `<Version>` in `CodesysMcpServer.Web.csproj` (the only source of truth).
The Release workflow publishes `v<Version>` and refuses to run if that tag already exists.

## Architecture

```
REST (Program.cs) ─┐
MCP  (Mcp/CodesysTools.cs) ─┴─► CodesysOperations ─► PythonRunner ─► CODESYS.exe running Scripts/<op>.py
```

- **One operation, two transports.** `Services/CodesysOperations.cs` is the only place that turns
  a request into a script run: validation, script selection, payload shape. `Program.cs` endpoints
  and `CodesysTools` methods are thin adapters that differ only in error reporting (REST:
  ProblemDetails with status codes; MCP: `McpException`). A new operation needs a script, a
  `CodesysOperations` method, a REST endpoint and an MCP tool, plus the docs.
- **Projects are never caller-supplied paths.** `ProjectCatalog` resolves the optional `project`
  argument (name or full path) against the configured `ProjectPath` + `AdditionalProjectPaths`
  (`MaxProjects` > 1). A configured file is a `.project` or a source `.library` (`kind`). Referenced
  libraries (the `library` argument of the read tools) are resolved from the project's own
  library references, never from the caller.
- **Script protocol** (`PythonRunner.cs` ↔ `Scripts/mcp_io.py`). The runner writes a JSON request
  file and passes its path to the script (`--scriptargs` under CODESYS). The script answers with
  the envelope `{ok, data, error{message, traceback, code}}`, written to `resultPath` and also to
  stdout between sentinel markers. Each operation script is a small `handler(request)` passed to
  `mcp_io.run(handler)`. `error.code` (`password_required` / `password_invalid`) maps to HTTP 401.
- **Persistent session** (`KeepSessionAlive`, the default). `CodesysSessionPool` keeps one
  `CodesysSession` per project. Each runs `CODESYS.exe --noUI --runscript=session_host.py`, which
  watches a queue directory under `WorkDirectory\sessions\<key>\`. Requests are moved in as
  `<id>.req.json`, the host loads the named script in hosted mode (`mcp_io.HOSTED_HANDLERS`),
  keeps the project open, reloads it when the file changes on disk, and discards unsaved changes
  after a failed request. Calls for one project are serialized. Individual operation scripts are
  re-read on every call, but changes to `codesys_api.py` / `mcp_io.py` only take effect after
  `POST /session/stop`. Scripts are copied to the build output, so rebuild after editing them.
- **`Scripts/codesys_api.py`** is the facade over the Scripting Engine: `Application.OpenProject`,
  `Project` (lazy tree scan that classifies objects by parsing their declaration text, because the
  engine exposes no reliable `is_pou`/`is_dut` flags), a Structured Text parser, `Compiler`,
  recipes, library lookup. Engine features differ between CODESYS versions, so the code probes
  attributes and methods defensively (`_try_call`, `getattr` fallbacks) instead of assuming them.
- **Settings** are written by `AppSettingsWriter` to `appsettings.production.json` next to the
  binary. That file is machine-local (git-ignored, excluded from publish), loaded last and
  reloaded on change, so it overrides `appsettings.json` and environment variables for the keys
  it contains.
- `Mcp/StdioProxy.cs` lets stdio-only MCP clients start the exe, which then forwards to the
  running HTTP server.

## Constraints

- The scripts run under CODESYS's IronPython 2.7 and must also run under CPython 3 (for
  `selftest.py`): use `from __future__ import print_function`, `u""` literals, and no f-strings
  or other Python 3-only syntax.
- `WorkDirectory` must not contain spaces: CODESYS splits `--scriptargs` on whitespace.
- While a session runs, CODESYS holds the project file open; the IDE cannot open it at the
  same time.

## Keep the docs up to date

Every change that users can see — a new or changed tool, endpoint, argument, response field,
setting or settings-page behaviour — updates the documentation in the same change:

- `README.md` (endpoint and tool tables, the relevant section);
- the pages under `docs/src/content/docs/` (in particular `reference/mcp-tools.md`,
  `guides/rest-api.mdx`, `guides/settings-page.mdx`, `reference/configuration.md`), adding a
  guide page and its `docs/astro.config.mjs` sidebar entry for a new feature;
- the `[Description]` texts in `Mcp/CodesysTools.cs`, which are what an MCP client's model reads.
