---
title: Configuration
description: appsettings.json options.
---

The server reads `appsettings.json` next to the executable, then
`appsettings.production.json` (written by the settings page) on top of it. You normally only
change settings through the [settings page](/CodesysMcpNet/guides/settings-page/); edit
`appsettings.json` for everything else.

## `Codesys` section

```jsonc
"Codesys": {
  "UseCodesys": true,                     // false -> run scripts under a plain Python interpreter (testing)
  "ExecutablePath": "C:\\Program Files\\CODESYS 3.5.20.0\\CODESYS\\Common\\CODESYS.exe",
  "ProjectPath": null,                    // the default .project every endpoint/tool acts on
  "MaxProjects": 1,                       // >1 allows AdditionalProjectPaths (one CODESYS each)
  "AdditionalProjectPaths": [],           // further projects, selected per call via "project"
  "Profile": "CODESYS V3.5 SP20 Patch 0", // must match an installed profile
  "NoUserInterface": true,                // start CODESYS with --noUI
  "AdditionalArguments": [],              // extra CODESYS.exe arguments
  "PythonExecutablePath": "python",       // only used when UseCodesys is false
  "ScriptsDirectory": "Scripts",
  "WorkDirectory": "C:\\ProgramData\\CodesysMcpNet\\work",
  "TimeoutSeconds": 1200,                 // per script
  "KeepTempFiles": false,                 // keep request/result files for troubleshooting
  "KeepSessionAlive": true,               // one long-lived CODESYS instead of one per call
  "StartSessionOnStartup": true,          // open the project as soon as the server starts
  "SessionIdleMinutes": 0                 // >0 stops CODESYS after that much idle time
}
```

`ExecutablePath`, `ProjectPath`, `Profile`, `MaxProjects` and `AdditionalProjectPaths` are what
the settings page edits; it writes them to `appsettings.production.json`. See
[Multiple projects](/CodesysMcpNet/guides/multiple-projects/) for the last two.

:::caution
`WorkDirectory` must not contain spaces: CODESYS splits its `--scriptargs` value on
whitespace. The server logs a warning if it does.
:::

## Listening address

```json
"Kestrel": {
  "Endpoints": {
    "Http": { "Url": "http://127.0.0.1:5088" }
  }
}
```

Change the port here if 5088 is taken, and update your MCP client configuration to match.
Keep the host `127.0.0.1` unless you really need remote access: the API can edit your project
and browse the server's disks, and it has no authentication.

## Logging

Logs go to the console and to rolling files in `Logs\` next to the executable (`FileLogging`
section: daily files, 20 MB size cap, 30 files kept). Every line a CODESYS script prints is
logged as it arrives.
