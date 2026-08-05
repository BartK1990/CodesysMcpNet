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

## Layout

```
/McpServer
  Program.cs                 Minimal API endpoints + MCP server registration
  /Models                    Request DTOs (+ DataAnnotations validation), shared by REST and MCP
  /Mcp
    CodesysTools.cs          [McpServerToolType] — one MCP tool per operation, calls CodesysOperations
  /Services
    CodesysOperations.cs     Shared implementation: validation, script selection, payload shaping
    PythonRunner.cs          Process host, live log streaming, JSON envelope handling
    CodesysOptions.cs        Configuration ("Codesys" section)
    RequestValidator.cs      DataAnnotations validation, shared by REST and MCP
    CodesysValidationException.cs
    ScriptExecutionException.cs
  /Logging                   Dependency-free rolling file logger
  /Scripts
    mcp_io.py                Request/result plumbing shared by every script
    codesys_api.py           Facade over the Scripting Engine + Structured Text parser
    selftest.py              Parser self-test (no CODESYS required)
    compile.py  structure.py
    pou_read.py   pou_update.py  pou_create.py
    gvl_read.py   gvl_create.py
    dut_read.py   dut_create.py
    enum_read.py  enum_create.py
```

## Endpoints

| Method | Route | Body / Query |
|---|---|---|
| GET  | `/structure`     | `projectPath` |
| GET  | `/pou/content`   | `projectPath`, `name` |
| GET  | `/gvl/content`   | `projectPath`, `name` |
| GET  | `/dut/content`   | `projectPath`, `name` |
| GET  | `/enum/content`  | `projectPath`, `name` |
| POST | `/pou/update`    | `{ projectPath, pouName, newCode, newDeclaration? }` |
| POST | `/pou/create`    | `{ projectPath, name, type, language, returnType?, parentPath?, declaration?, implementation? }` |
| POST | `/gvl/create`    | `{ projectPath, name, parentPath?, variables?: [{name,type,initialValue?,comment?}] }` |
| POST | `/dut/create`    | `{ projectPath, name, fields: [{name,type,initialValue?,comment?}], baseType?, parentPath? }` |
| POST | `/enum/create`   | `{ projectPath, name, values: ["Idle := 3","Busy"], baseType?, parentPath? }` |
| POST | `/compile`       | `{ projectPath, clean?, saveAfterCompile? }` |
| GET  | `/health`        | – |

Status codes: `200` success, `400` invalid request or missing project file,
`502` the script failed (the ProblemDetails body carries `script`, `exitCode`,
`pythonTraceback` and `stderr`), `499` client disconnected mid-run.

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
  "Profile": "CODESYS V3.5 SP20 Patch 0", // must match an installed profile
  "NoUserInterface": true,
  "PythonExecutablePath": "python",       // only used when UseCodesys is false
  "ScriptsDirectory": "Scripts",
  "WorkDirectory": "C:\\ProgramData\\CodesysMcpNet\\work",
  "TimeoutSeconds": 600,
  "KeepTempFiles": false
}
```

**Set `ExecutablePath` and `Profile` to match your installation** — the exact profile
name is what `CODESYS.exe --profile=` expects (see the CODESYS installation directory).

`WorkDirectory` should contain **no spaces**: CODESYS splits its `--scriptargs` value on
whitespace. The server logs a warning if it does.

Every script runs serialized behind a semaphore, because CODESYS is effectively a
single-instance application. Expect tens of seconds per call — most of it is CODESYS
start-up, not the script.

## Logging

Console **and** rolling files under `Logs/` (next to the binary), configured via the
`FileLogging` section: daily rolling, 20 MB size cap, 30 files retained. Every line the
Python script prints is logged the moment it arrives, so CODESYS progress is visible live.

## Running

```bash
dotnet run --project McpServer/McpServer.csproj
```

Listens on `http://127.0.0.1:5088` (see the `Kestrel` section in `appsettings.json`).

```bash
curl "http://127.0.0.1:5088/structure?projectPath=C:\demo\Plc.project"
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
