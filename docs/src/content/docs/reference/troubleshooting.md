---
title: Troubleshooting
description: Common problems and how to fix them.
---

### Every call returns 400 "no project configured"

Open [http://127.0.0.1:5088/](http://127.0.0.1:5088/), select a CODESYS.exe and a project, and
click **Save**.

### The session stays in "Starting…" or ends with an error

- Check that the **profile** matches the installation — CODESYS may fail to start or
  hang on an invisible dialog in `--noUI` mode with a wrong one.
- Make sure the project isn't open in the CODESYS IDE.
- Look at the newest file in `Logs\`; every line CODESYS prints is there.
- Try opening the project once in the IDE with the same profile: missing libraries or device
  descriptions can also block a scripted open.

### The CODESYS IDE says the project is in use

The persistent session holds it open. Click **Stop** on the settings page first.

### A call fails with 502

The script ran but failed. The response (or the MCP tool error) contains the Python traceback.
Common causes: a misspelled object name, invalid Structured Text in `newCode`, or an object
that already exists.

### Port 5088 is already in use

Change `Kestrel:Endpoints:Http:Url` in `appsettings.json` (see
[Configuration](/CodesysMcpNet/reference/configuration/)).

### The `win-x64` package doesn't start

It needs the [ASP.NET Core 10 Runtime](https://dotnet.microsoft.com/download/dotnet/10.0).
Install it, or use the **portable** package instead.
