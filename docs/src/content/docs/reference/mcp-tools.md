---
title: MCP tools
description: The tools the server exposes to MCP clients.
---

All tools act on the project configured on the
[settings page](/CodesysMcpNet/guides/settings-page/). A failed validation or script run is
returned to the client as a tool error whose message carries the details (including the
Python traceback).

## Read

| Tool | Inputs | Returns |
|---|---|---|
| `structure` | – | Full project structure: applications, folders, POUs, GVLs, DUTs and ENUMs. |
| `pou_content` | `name` | Declaration and implementation of a POU. Use `Parent.Member` for a method, action, property or transition (e.g. `FB_Motor.Reset`) and `Parent.Property.Get` for a property accessor. |
| `gvl_content` | `name`, `filter?` | Variables of a GVL with types and initial values. `filter` is a case-insensitive wildcard (`*Fault*`, `x?Run`) or substring; with a filter the full declaration text is omitted. |
| `dut_content` | `name` | Fields of a STRUCT/UNION DUT. |
| `enum_content` | `name` | Values of an ENUM. |
| `search_text` | `pattern`, `regex?`, `caseSensitive?`, `ignoreComments?`, `maxResults?` | One hit per matching line in all declarations and implementations: POU, member, section, line number and text. Graphical bodies (FBD/LD/CFC/SFC) are not searchable and are listed separately. |
| `task_config` | – | Every task with kind, priority, interval, event, watchdog and the POUs it calls, in call order. |

## Write

| Tool | Inputs | Effect |
|---|---|---|
| `pou_update` | `pouName`, `newCode`, `newDeclaration?` | Replaces a POU's implementation (and optionally its declaration). |
| `pou_create` | `name`, `type` (`PRG`/`FB`/`FUN`), `language` (`ST`, `IL`, `LD`, `FBD`, `SFC`, `CFC`), `returnType?`, `parentPath?`, `declaration?`, `implementation?` | Creates a POU. |
| `gvl_create` | `name`, `parentPath?`, `variables?` | Creates a global variable list. |
| `dut_create` | `name`, `fields`, `baseType?`, `parentPath?` | Creates a STRUCT. |
| `enum_create` | `name`, `values` (e.g. `["Idle := 3", "Busy"]`), `baseType?`, `parentPath?` | Creates an ENUM. |

## Build

| Tool | Inputs | Effect |
|---|---|---|
| `compile` | `clean?`, `saveAfterCompile?` | Generates code for every application and returns the verdict. `messagesAvailable` tells whether the compiler message list could be read on this CODESYS version; `success` is always meaningful. |
