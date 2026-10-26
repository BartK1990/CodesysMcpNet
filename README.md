# CodesysMcpNet

An ASP.NET Core 10 host that manipulates a CODESYS V3 project by executing Python scripts
against the **official CODESYS Scripting Engine**, exposed both as a plain REST/JSON API
and as a native [MCP](https://modelcontextprotocol.io) server — the same operations, on
the same Kestrel instance, over two protocols.

```
REST request  ──► Program.cs endpoint     ──┐
MCP tool call ──► Mcp/CodesysTools.cs /mcp ──┴─► CodesysOperations ──► PythonRunner ──► CODESYS.exe --runscript=<script>.py
                                                                                                    │
                                    JSON envelope ◄── result file + stdout ◄───────────────────────┘
```
<img width="649" height="800" alt="CodesysMcpIntro" src="https://github.com/user-attachments/assets/27fa8508-1fae-4da1-a442-8401e9313e9e" />

`CodesysOperations` (see [Layout](#layout)) is the only place that knows how to turn a
request into a script run — validation, script selection, payload shaping. The REST
endpoints and the MCP tools are both thin adapters on top of it that differ only in how
they report success/failure for their protocol.

Every operation acts on **one** CODESYS executable and, by default, **one** project, picked
on the [settings page](#settings-page) served at `/` — no endpoint or tool takes an arbitrary
project path as input. Raise `MaxProjects` to configure several projects; callers then pick
one of those by name (see [Multiple projects](#multiple-projects)).

📖 **Documentation** (installation, settings page walkthrough with screenshots, MCP client
setup): <https://bartk1990.github.io/CodesysMcpNet/>

⬇️ **Download**: [latest release](https://github.com/BartK1990/CodesysMcpNet/releases/latest) —
`win-x64` (needs the ASP.NET Core 10 runtime) or `win-x64-portable` (self-contained, unzip and run).

## Layout

```
/McpServer
  Program.cs                 Minimal API endpoints + MCP server registration
  /wwwroot
    index.html               Settings page: CODESYS.exe path + project path, served at "/"
  /Models                    Request DTOs (+ DataAnnotations validation), shared by REST and MCP
    SettingsRequest.cs       Body of POST /settings
  /Mcp
    CodesysTools.cs          [McpServerToolType] — one MCP tool per operation, calls CodesysOperations
  /Services
    CodesysOperations.cs     Shared implementation: validation, script selection, payload shaping
    PythonRunner.cs          Process host, live log streaming, JSON envelope handling
    CodesysSession.cs        Persistent CODESYS instance fed through a queue directory
    CodesysOptions.cs        Configuration ("Codesys" section), incl. ExecutablePath + ProjectPath + MaxProjects
    ProjectCatalog.cs        Configured projects; resolves a call's optional "project" argument
    CodesysSessionPool.cs    One persistent session (+ gate) per project, stops removed ones
    AppSettingsWriter.cs     Reads/writes appsettings.production.json for the settings page
    SettingsSnapshot.cs      Response shape of GET/POST /settings
    FileBrowserService.cs    Drive/folder/file listing backing the settings page's path picker
    FileBrowserEntry.cs      Response shape of GET /files
    RequestValidator.cs      DataAnnotations validation, shared by REST and MCP
    CodesysValidationException.cs
    ScriptExecutionException.cs
  /Logging                   Dependency-free rolling file logger
  /Scripts
    mcp_io.py                Request/result plumbing shared by every script
    codesys_api.py           Facade over the Scripting Engine + Structured Text parser
    selftest.py              Parser self-test (no CODESYS required)
    session_host.py          Long-running host script of the persistent session
    ping.py                  Opens the project only (session warm-up)
    compile.py  structure.py
    pou_read.py   pou_update.py  pou_create.py
    gvl_read.py   gvl_create.py
    dut_read.py   dut_create.py
    enum_read.py  enum_create.py
    search_text.py  task_config.py
```

## Settings page

`http://127.0.0.1:5088/` serves [wwwroot/index.html](McpServer/wwwroot/index.html): two
fields — CODESYS.exe path and project (`.project`) file path — pre-filled from the current
configuration, each showing whether the path actually exists on this machine. **Save**
`POST`s to `/settings`, which validates both paths and writes them to
`Codesys:ExecutablePath` / `Codesys:ProjectPath` in `appsettings.production.json`, created
or updated next to the running binary. That file is loaded as a reloading configuration
source (see [Program.cs](McpServer/Program.cs)), so a save takes effect within a couple of
seconds — no restart needed.

`appsettings.production.json` is intentionally **not** built, published, or committed: it's
excluded from the project's `Content` items in
[McpServer.csproj](McpServer/McpServer.csproj) and listed in `.gitignore`. It only ever
exists as a machine-local file that [AppSettingsWriter](McpServer/Services/AppSettingsWriter.cs)
creates the first time someone saves settings.

Each field has a **Browse…** button that opens an in-page file picker instead of typing a
path by hand. A browser page has no way to learn the real absolute path of a file chosen
through `<input type="file">` — it only ever gets a fake one, by design — so the picker
isn't a native OS dialog; it's a small file explorer driven by
[FileBrowserService](McpServer/Services/FileBrowserService.cs) over `GET /files`, which
walks the server's own filesystem (drives → folders → files, filtered to `.exe` or
`.project`) since the server already has full local access to it anyway.

| Method | Route | Body / Query |
|---|---|---|
| GET  | `/settings` | – → `{ executablePath, projectPath, profile, executableExists, projectExists, maxProjects, maxProjectsLimit, additionalProjects: [{path, exists}] }` |
| POST | `/settings` | `{ executablePath, projectPath, profile?, maxProjects?, additionalProjectPaths? }` → same shape, `400` if a path doesn't exist or there are more projects than `maxProjects` |
| GET  | `/files` | `path?` (omit for the drive list), `filter?` (e.g. `.exe`) → `{ path, parent, entries: [{name, fullPath, isDirectory}] }` |

## Endpoints

Every operation below acts on the default project configured on the
[settings page](#settings-page). Each one (and the `/session` routes) also takes an optional
`project` query parameter naming another configured project — see
[Multiple projects](#multiple-projects).

| Method | Route | Body / Query |
|---|---|---|
| GET  | `/structure`     | – |
| GET  | `/pou/content`   | `name` — a POU, or `Parent.Member` for a method/action/property/transition |
| GET  | `/gvl/content`   | `name`, `filter?` (`*Fault*` wildcard or substring; omits the full declaration) |
| GET  | `/dut/content`   | `name` |
| GET  | `/enum/content`  | `name` |
| GET  | `/search`        | `pattern`, `regex?`, `caseSensitive?`, `ignoreComments?`, `maxResults?` (default 200, max 5000) |
| GET  | `/tasks`         | – (kind, priority, interval, event trigger, watchdog and called POUs per task) |
| POST | `/pou/update`    | `{ pouName, newCode, newDeclaration? }` |
| POST | `/pou/create`    | `{ name, type, language, returnType?, parentPath?, declaration?, implementation? }` |
| POST | `/gvl/create`    | `{ name, parentPath?, variables?: [{name,type,initialValue?,comment?}] }` |
| POST | `/dut/create`    | `{ name, fields: [{name,type,initialValue?,comment?}], baseType?, parentPath? }` |
| POST | `/enum/create`   | `{ name, values: ["Idle := 3","Busy"], baseType?, parentPath? }` |
| POST | `/compile`       | `{ clean?, saveAfterCompile? }` |
| GET  | `/health`        | – |
| GET  | `/version`       | – (`{ "version": "1.0.0" }`) |
| GET  | `/projects`      | – (configured projects, default first, with their session state) |
| GET  | `/sessions`      | – (session status of every configured project) |
| POST | `/projects/password` | `{ project?, password }` (password of a password-protected project; memory only, empty forgets it) |
| GET  | `/session`       | – (persistent CODESYS status) |
| POST | `/session/start` | – (start CODESYS and open the project) |
| POST | `/session/stop`  | – (stop CODESYS, releasing the project file) |

Status codes: `200` success, `400` invalid request, no project configured, `project` names
no configured project, or the project file doesn't exist, `401` the project is password
protected and its password is missing (`code: password_required`) or wrong
(`password_invalid`) — enter it on the settings page, `502` the script failed (the
ProblemDetails body carries `script`, `exitCode`, `pythonTraceback` and `stderr`), `499`
client disconnected mid-run.

`type` accepts `PRG` / `FB` / `FUN`; `language` accepts `ST`, `IL`, `LD`, `FBD`, `SFC`, `CFC`.

## MCP tools

The same thirteen operations are exposed as MCP tools at `POST /mcp` (Streamable HTTP
transport), registered in [Program.cs](McpServer/Program.cs) via
`AddMcpServer().WithHttpTransport().WithTools<CodesysTools>()` and implemented in
[Mcp/CodesysTools.cs](McpServer/Mcp/CodesysTools.cs). Tool names and inputs mirror the
REST routes:

| Tool | Equivalent REST route |
|---|---|
| `structure` | `GET /structure` |
| `pou_content` | `GET /pou/content` |
| `gvl_content` | `GET /gvl/content` |
| `dut_content` | `GET /dut/content` |
| `enum_content` | `GET /enum/content` |
| `search_text` | `GET /search` |
| `task_config` | `GET /tasks` |
| `pou_update` | `POST /pou/update` |
| `pou_create` | `POST /pou/create` |
| `gvl_create` | `POST /gvl/create` |
| `dut_create` | `POST /dut/create` |
| `enum_create` | `POST /enum/create` |
| `compile` | `POST /compile` |
| `projects` | `GET /projects` |

Every tool except `projects` takes an optional `project` argument (see
[Multiple projects](#multiple-projects)).

A failed validation or script run raises `McpException`, so its message reaches the
calling model as a tool error — the same detail the REST layer puts in a ProblemDetails
body, just without the HTTP status code or `exitCode`/`stderr` extensions (those are
REST-specific; on the MCP side the message text carries the traceback instead).

## Configuration (`appsettings.json`)

```jsonc
"Codesys": {
  "UseCodesys": true,                     // false -> run scripts under a plain interpreter
  "ExecutablePath": "C:\\Program Files\\CODESYS 3.5.20.0\\CODESYS\\Common\\CODESYS.exe",
  "ProjectPath": null,                    // the default .project every endpoint/tool acts on
  "MaxProjects": 1,                       // >1 allows AdditionalProjectPaths (one CODESYS each)
  "AdditionalProjectPaths": [],           // further projects, selected per call via "project"
  "Profile": "CODESYS V3.5 SP20 Patch 0", // must match an installed profile
  "NoUserInterface": true,
  "PythonExecutablePath": "python",       // only used when UseCodesys is false
  "ScriptsDirectory": "Scripts",
  "WorkDirectory": "C:\\ProgramData\\CodesysMcpNet\\work",
  "TimeoutSeconds": 1200,
  "KeepTempFiles": false,
  "KeepSessionAlive": true,               // one long-lived CODESYS instead of one per call
  "StartSessionOnStartup": true,          // open the project as soon as the server starts
  "SessionIdleMinutes": 0                 // >0 stops CODESYS after that much idle time
}
```

`ExecutablePath`, `ProjectPath`, `Profile`, `MaxProjects` and `AdditionalProjectPaths` are
the fields the [settings page](#settings-page) edits, and it writes them to `appsettings.production.json`, not this file — treat the
values above as first-run defaults / a template for that generated file, not something you
need to hand-edit day to day.

**Set `ExecutablePath` and `Profile` to match your installation** — the exact profile
name is what `CODESYS.exe --profile=` expects (see the CODESYS installation directory).

`WorkDirectory` should contain **no spaces**: CODESYS splits its `--scriptargs` value on
whitespace. The server logs a warning if it does.

Scripts for one project run serialized behind a semaphore, because a CODESYS instance can
only run one script at a time. One-shot runs (`KeepSessionAlive: false`) are serialized
globally.

### Persistent session

Starting CODESYS and opening a project takes 30–60 s, so by default (`KeepSessionAlive`)
the server does it once: `CODESYS.exe --noUI --runscript=session_host.py` stays running
with the project open, and each request is a JSON file moved into
`<WorkDirectory>\sessions\<key>\`, which the host claims, runs and answers through the usual
result file. Warm calls take a second or two instead of the full start-up.

* The first request (or server start-up, with `StartSessionOnStartup`) pays the start-up.
* The host reloads the project if the `.project` file changes on disk, switches when a
  different project is configured, and restarts when the executable/profile changes.
* A request that fails with unsaved changes has those changes discarded (project closed
  without saving), as a failed one-shot run would.
* While the session runs **CODESYS holds the project open**, so opening it in the CODESYS
  IDE at the same time is not supported. `POST /session/stop` (or `SessionIdleMinutes`)
  releases it; the next call starts it again.
* A timed-out request kills the session; the host also exits by itself if the server
  process disappears.
* Edits to `codesys_api.py` / `mcp_io.py` take effect after `POST /session/stop`
  (individual operation scripts are re-read on every call).

### Multiple projects

`MaxProjects` (default `1`, up to `10`) controls how many projects can be configured. With 1
nothing changes: there is one project and one shared session. Raise it and add
`AdditionalProjectPaths` (or use **Max projects** / **Additional projects** on the settings
page), and:

* every tool and endpoint takes an optional `project` — a configured project's file name
  without `.project` (case-insensitive) or its full path; omitted means `ProjectPath`. Only
  configured projects can be selected. The `projects` tool / `GET /projects` lists them.
* with `KeepSessionAlive`, each project gets **its own CODESYS instance** with the project kept
  open: no reload when alternating between projects, and calls for different projects run in
  parallel (calls for the same project are still serialized). Each instance costs memory.
* `StartSessionOnStartup` warms up every configured project; removing one (or lowering
  `MaxProjects`) stops its session and releases the file.

The [settings page](#settings-page) shows the session state (Stopped / Starting / Ready /
Busy / Stopping, with the running script, uptime and last error) with **Start** / **Stop**
buttons — one row per configured project, each started and stopped independently; it polls
`GET /sessions`.

Set `KeepSessionAlive` to `false` to go back to one CODESYS process per call.

## Logging

Console **and** rolling files under `Logs/` (next to the binary), configured via the
`FileLogging` section: daily rolling, 20 MB size cap, 30 files retained. Every line the
Python script prints is logged the moment it arrives, so CODESYS progress is visible live.

## Running

```bash
dotnet run --project McpServer/McpServer.csproj
```

Listens on `http://127.0.0.1:5088` (see the `Kestrel` section in `appsettings.json`).
Open `http://127.0.0.1:5088/` first and save a CODESYS.exe path and a project path — every
call below fails with `400` until that's done.

```bash
curl http://127.0.0.1:5088/structure
```

## Versioning and releases

The release version is defined once, as `<Version>` in
[CodesysMcpServer.Web.csproj](CodesysMcpServer.Web/CodesysMcpServer.Web.csproj). It is shown
next to the title on the settings page, returned by `GET /version` and `GET /health`, and
printed in the startup log.

To release: bump `<Version>`, push, then run **Actions → Release → Run workflow**
([.github/workflows/release.yml](.github/workflows/release.yml)). It builds the `win-x64`
(framework-dependent) and `win-x64-portable` (self-contained single file) zips and publishes
them as GitHub release `v<Version>`. It refuses to run if that tag already exists.

## Documentation site

The [Starlight](https://starlight.astro.build/) site in [docs/](docs/) is deployed to GitHub
Pages by [.github/workflows/docs.yml](.github/workflows/docs.yml) on every push to `master`
that touches `docs/`. Run it locally with `cd docs && npm ci && npm run dev`; regenerate the
web UI screenshots with `npm run screenshots` while the server is running.

## Connecting from Claude Code, OpenCode, or any other MCP client

With the server running, point an MCP client at `http://127.0.0.1:5088/mcp` using the
HTTP (Streamable HTTP) transport — no bridge or adapter needed, it's a real MCP endpoint.

**Claude Code**:

```bash
claude mcp add --transport http codesys http://127.0.0.1:5088/mcp
```

or, for a project-scoped, team-shared entry, add it to `.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "codesys": {
      "type": "http",
      "url": "http://127.0.0.1:5088/mcp"
    }
  }
}
```

**OpenCode** (`opencode.json` / `opencode.jsonc`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "codesys": {
      "type": "remote",
      "url": "http://127.0.0.1:5088/mcp",
      "enabled": true
    }
  }
}
```

Both clients will then list `structure`, `pou_content`, `pou_update`, `compile`, … as
ordinary tools (see [MCP tools](#mcp-tools)). The server must already be running — start
it as described under [Running](#running) before adding it to either client.

## The scripting facade

The API surface used by the scripts (`Application()`, `OpenProject()`, `project.Pous`,
`pou.SetText()`, `gvl.Variables`, `dut.Elements`, `enum.Values`, `compiler.Compile()`,
`project.Save()`, …) does not exist in the engine itself. The engine injects the globals
`system` and `projects`, and works with `projects.open()`, `object.get_children()`,
`object.textual_declaration.replace()`, `create_pou()`, `create_dut()`, `create_gvl()`.

`codesys_api.py` is the adapter: the documented surface on the outside, the official API
on the inside. It also contains a Structured Text parser (comment/pragma/string aware)
that turns declarations into the variable, field and enumerator lists the endpoints return.

Version-tolerant by design: enum members (`PouType`, `ImplementationLanguages`, `DutType`),
build entry points (`generate_code` / `build` / `check`) and object flags are all probed
against several candidate names, so the scripts survive engine differences between
CODESYS releases.

### Known version-dependent spot

Reading the **compiler message list** is the one thing that differs materially between
engine versions, and some do not expose a message store to scripts at all.
`_collect_messages()` probes the known accessors and the `/compile` response reports
`messagesAvailable` so you can tell whether `messages` is authoritative. The `success`
flag is always meaningful: it also reflects whether the build call itself threw.

## Verifying without CODESYS

The ST parser and declaration generators run standalone:

```bash
C:\Development\Python\Python314\python.exe McpServer/Scripts/selftest.py
```

To exercise the whole HTTP → script → JSON pipeline without CODESYS, set
`Codesys:UseCodesys=false`, point `Codesys:PythonExecutablePath` at a Python interpreter,
and put a module on `PYTHONPATH` that injects `system` / `projects` / `PouType` /
`ImplementationLanguages` / `DutType` into `builtins`.
