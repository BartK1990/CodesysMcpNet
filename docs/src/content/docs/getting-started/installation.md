---
title: Installation
description: Download and start the CODESYS MCP Server on Windows.
---

## Download

Grab the latest release from the
[Releases page](https://github.com/BartK1990/CodesysMcpNet/releases/latest). Each release
has two packages:

| Package | Size | Needs | Pick it when |
|---|---|---|---|
| `CodesysMcpServer-<version>-win-x64.zip` | ~3 MB | [ASP.NET Core 10 Runtime](https://dotnet.microsoft.com/download/dotnet/10.0) | .NET 10 is already installed, or you want security updates of the runtime through Windows Update. |
| `CodesysMcpServer-<version>-win-x64-portable.zip` | ~50 MB | nothing | You want to unzip and run, e.g. on an engineering PC where you can't install software. |

Both packages contain the same application. `SHA256SUMS.txt` lists the checksums of the
zip files.

## Install

1. Unzip the package into a folder you can write to, e.g. `C:\Tools\CodesysMcpServer`.
   The server writes its machine-local settings (`appsettings.production.json`) and its
   `Logs` folder next to the executable, so avoid `C:\Program Files` unless you run it as an
   administrator or as a [Windows service](/CodesysMcpNet/guides/windows-service/).
2. If Windows marks the zip as downloaded from the internet, right-click it →
   **Properties** → **Unblock** before unzipping.

## Start

Run `CodesysMcpServer.Web.exe`. A console window opens and logs:

```
CODESYS MCP server 1.0.0 starting. REST on this Kestrel instance, MCP tools at /mcp. …
Now listening on: http://127.0.0.1:5088
```

The server only listens on `127.0.0.1`, so it is reachable from this PC only.

Now open [http://127.0.0.1:5088/](http://127.0.0.1:5088/) and continue with
[First run](/CodesysMcpNet/getting-started/first-run/).

## Updating

Stop the server, unzip the new release over the old folder and start it again. Your settings
in `appsettings.production.json` are not part of the package, so they are kept.

The running version is shown next to the title on the settings page and returned by
`GET /version`.
