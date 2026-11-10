---
title: Libraries
description: Edit a CODESYS library directly, or read the libraries a project references.
---

The server works with CODESYS libraries in two ways:

- **A library file as the project.** Configure a source `.library` file instead of a
  `.project` file, and every tool reads and edits the library.
- **Libraries a project references.** The read tools take an optional `library` argument
  and read a referenced library's code instead of the project's. This is read-only.

## Editing a library

A source library (`.library`) can be configured anywhere a `.project` can: as the default
project on the [settings page](/CodesysMcpNet/guides/settings-page/) or as one of the
[additional projects](/CodesysMcpNet/guides/multiple-projects/). **Browse…** lists both file
types.

Once it is configured, the library behaves like a project. The read tools (`structure`,
`pou_content`, `gvl_content`, ...) show its contents, and the write tools (`pou_create`,
`pou_update`, `gvl_create`, `dut_create`, `enum_create`) change it. `compile` checks it.

A few things differ from a project:

- `projects` (`GET /projects`) reports `kind: "library"` (`"project"` for a `.project` file).
- `structure` also reports `kind`. For a library, it adds `libraryInfo`: title, version,
  company, default namespace, author, description, category and placeholder, taken from the
  library's Project Information.
- A library has no application to generate code for, so `compile` checks its objects instead,
  like **Build → Check all pool objects** in the IDE.
- `task_config` and `recipes` return empty lists, because a library has no tasks or Recipe
  Managers.
- The `project` argument accepts the file name with or without `.library`, for example
  `EasyModbusLib 1.0.11`.

Compiled libraries (`.compiled-library`, `.compiled-library-v3`) carry no source and cannot be
configured. Use the library's source `.library` file instead.

:::caution
While its session runs, CODESYS keeps the library open, just as it does with a project. Close
the library in the CODESYS IDE before the server opens it, or stop the session on the settings
page before you open it in the IDE.
:::

## Reading referenced libraries

A library's code lives in the library, not in the project that uses it. The `libraries` tool
(`GET /libraries`) lists the project's library references with their placeholder, namespace,
resolution and `source`. `source` is the file the library can be read from, or null when none
was found. The server looks for that file in this order:

1. in the library repositories (`<root>/<company>/<title>/<version>/`, the newest version for a
   `*` reference);
2. next to the project, named after the library (`Title.library`, `Title_1.2.3.library`).

Pass a title, placeholder or namespace from that list as the `library` argument of
`structure`, `pou_content`, `gvl_content`, `dut_content`, `enum_content` or `search_text`. The
tool then reads that library's source file. Only source libraries can be read this way. To
change a library, configure its `.library` file as a project
(see [Editing a library](#editing-a-library)).
