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

`CodesysOperations` (see [Layout](#layout)) is the only place that knows how to turn a
request into a script run — validation, script selection, payload shaping. The REST
endpoints and the MCP tools are both thin adapters on top of it that differ only in how
they report success/failure for their protocol.

Every operation acts on **one** CODESYS executable and **one** project, picked on the
[settings page](#settings-page) served at `/` — no endpoint or tool takes a project path
as input.

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
    CodesysOptions.cs        Configuration ("Codesys" section), incl. ExecutablePath + ProjectPath
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
| GET  | `/settings` | – → `{ executablePath, projectPath, executableExists, projectExists }` |
| POST | `/settings` | `{ executablePath, projectPath }` → same shape, `400` if either path doesn't exist |
| GET  | `/files` | `path?` (omit for the drive list), `filter?` (e.g. `.exe`) → `{ path, parent, entries: [{name, fullPath, isDirectory}] }` |

## Endpoints

Every operation below acts on the project configured on the [settings page](#settings-page)
— none of them take a project path as input anymore.

| Method | Route | Body / Query |
|---|---|---|
| GET  | `/structure`     | – |
| GET  | `/pou/content`   | `name` |
| GET  | `/gvl/content`   | `name` |
| GET  | `/dut/content`   | `name` |
| GET  | `/enum/content`  | `name` |
| POST | `/pou/update`    | `{ pouName, newCode, newDeclaration? }` |
| POST | `/pou/create`    | `{ name, type, language, returnType?, parentPath?, declaration?, implementation? }` |
| POST | `/gvl/create`    | `{ name, parentPath?, variables?: [{name,type,initialValue?,comment?}] }` |
| POST | `/dut/create`    | `{ name, fields: [{name,type,initialValue?,comment?}], baseType?, parentPath? }` |
| POST | `/enum/create`   | `{ name, values: ["Idle := 3","Busy"], baseType?, parentPath? }` |
| POST | `/compile`       | `{ clean?, saveAfterCompile? }` |
| GET  | `/health`        | – |
| GET  | `/session`       | – (persistent CODESYS status) |
| POST | `/session/start` | – (start CODESYS and open the project) |
| POST | `/session/stop`  | – (stop CODESYS, releasing the project file) |

Status codes: `200` success, `400` invalid request, no project configured, or the
configured project file doesn't exist, `502` the script failed (the ProblemDetails body
carries `script`, `exitCode`, `pythonTraceback` and `stderr`), `499` client disconnected
mid-run.

`type` accepts `PRG` / `FB` / `FUN`; `language` accepts `ST`, `IL`, `LD`, `FBD`, `SFC`, `CFC`.

## MCP tools

The same eleven operations are exposed as MCP tools at `POST /mcp` (Streamable HTTP
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
| `pou_update` | `POST /pou/update` |
| `pou_create` | `POST /pou/create` |
| `gvl_create` | `POST /gvl/create` |
| `dut_create` | `POST /dut/create` |
| `enum_create` | `POST /enum/create` |
| `compile` | `POST /compile` |

A failed validation or script run raises `McpException`, so its message reaches the
calling model as a tool error — the same detail the REST layer puts in a ProblemDetails
body, just without the HTTP status code or `exitCode`/`stderr` extensions (those are
REST-specific; on the MCP side the message text carries the traceback instead).

## Configuration (`appsettings.json`)

```jsonc
"Codesys": {
  "UseCodesys": true,                     // false -> run scripts under a plain interpreter
  "ExecutablePath": "C:\\Program Files\\CODESYS 3.5.20.0\\CODESYS\\Common\\CODESYS.exe",
  "ProjectPath": null,                    // the .project every endpoint/tool acts on
  "Profile": "CODESYS V3.5 SP20 Patch 0", // must match an installed profile
  "NoUserInterface": true,
  "PythonExecutablePath": "python",       // only used when UseCodesys is false
  "ScriptsDirectory": "Scripts",
  "WorkDirectory": "C:\\ProgramData\\CodesysMcpNet\\work",
  "TimeoutSeconds": 600,
  "KeepTempFiles": false,
  "KeepSessionAlive": true,               // one long-lived CODESYS instead of one per call
  "StartSessionOnStartup": true,          // open the project as soon as the server starts
  "SessionIdleMinutes": 0                 // >0 stops CODESYS after that much idle time
}
```

`ExecutablePath` and `ProjectPath` are the two fields the [settings page](#settings-page)
edits, and it writes them to `appsettings.production.json`, not this file — treat the
values above as first-run defaults / a template for that generated file, not something you
need to hand-edit day to day.

**Set `ExecutablePath` and `Profile` to match your installation** — the exact profile
name is what `CODESYS.exe --profile=` expects (see the CODESYS installation directory).

`WorkDirectory` should contain **no spaces**: CODESYS splits its `--scriptargs` value on
whitespace. The server logs a warning if it does.

Every script runs serialized behind a semaphore, because CODESYS is effectively a
single-instance application.

### Persistent session

Starting CODESYS and opening a project takes 30–60 s, so by default (`KeepSessionAlive`)
the server does it once: `CODESYS.exe --noUI --runscript=session_host.py` stays running
with the project open, and each request is a JSON file moved into
`<WorkDirectory>\session\`, which the host claims, runs and answers through the usual
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

The [settings page](#settings-page) shows the session state (Stopped / Starting / Ready /
Busy / Stopping, with the running script, uptime and last error) and has **Start** / **Stop**
buttons; it polls `GET /session`.

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
