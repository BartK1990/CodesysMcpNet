---
title: Introduction
description: What the CODESYS MCP Server is and how it works.
---

**CODESYS MCP Server** is a small Windows application that lets AI assistants (Claude Code,
OpenCode, Claude Desktop, …) and your own scripts work on a **CODESYS V3** project: read the
project tree and source code, search it, create and update POUs, GVLs, DUTs and ENUMs, and
compile it.

It exposes the same set of operations over two protocols, on the same local web server:

- **MCP** (Model Context Protocol) at `http://127.0.0.1:5088/mcp` — for AI assistants.
- **REST/JSON** at `http://127.0.0.1:5088/…` — for scripts, CI jobs, or manual testing.

## How it works

```
MCP client / REST call
        │
        ▼
CODESYS MCP Server (http://127.0.0.1:5088)
        │   one Python script per operation
        ▼
CODESYS.exe --noUI  (official Scripting Engine, project kept open)
        │
        ▼
your .project file
```

Every request runs a Python script inside the **official CODESYS Scripting Engine**. The server
never parses or writes the `.project` file itself, so whatever it does is exactly what the
CODESYS IDE would do.

Every operation acts on **one CODESYS installation and one project**, chosen on the
[settings page](/CodesysMcpNet/guides/settings-page/). No tool or endpoint takes a project path
as input — so an assistant can only ever touch the project you selected.

## Requirements

- Windows x64.
- CODESYS V3.5 (with the Scripting Engine, which is part of a standard installation).
- For the `win-x64` package only: the
  [ASP.NET Core 10 Runtime](https://dotnet.microsoft.com/download/dotnet/10.0). The
  **portable** package needs nothing else.

Next: [install the server](/CodesysMcpNet/getting-started/installation/).
