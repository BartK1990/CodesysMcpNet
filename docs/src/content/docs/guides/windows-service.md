---
title: Run as a Windows service
description: Start the server automatically with Windows.
---

The executable can run as a Windows service, so it starts with Windows and needs no console
window. Run these in an **elevated** PowerShell, adjusting the path:

```powershell
New-Service -Name CodesysMcpServer `
  -BinaryPathName '"C:\Tools\CodesysMcpServer\CodesysMcpServer.Web.exe"' `
  -DisplayName 'CODESYS MCP Server' `
  -StartupType Automatic
Start-Service CodesysMcpServer
```

To remove it:

```powershell
Stop-Service CodesysMcpServer
sc.exe delete CodesysMcpServer
```

Things to keep in mind:

- A service runs as **LocalSystem** by default. CODESYS licences, profiles and plug-ins are
  often installed per user; if CODESYS fails to start from the service, configure the service
  to log on as the user that normally runs CODESYS (*services.msc → Properties → Log On*).
- The account must be able to write to the server folder (`appsettings.production.json`,
  `Logs\`) and to the `WorkDirectory` (default `C:\ProgramData\CodesysMcpNet\work`).
- Logs go to the `Logs` folder next to the executable.
