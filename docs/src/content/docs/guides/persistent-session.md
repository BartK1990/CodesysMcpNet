---
title: Persistent session
description: How the server keeps CODESYS running between calls.
---

Starting CODESYS and opening a project takes 30–60 seconds. By default
(`KeepSessionAlive: true`) the server pays that only once: it runs
`CODESYS.exe --noUI --runscript=session_host.py`, keeps the project open, and hands each
request to that instance. Warm calls take a second or two.

- With `StartSessionOnStartup` (default), CODESYS is started as soon as the server starts and
  a project is configured. Otherwise the first call starts it.
- If the `.project` file changes on disk, the project is reloaded. If a different project is
  saved on the settings page, the session switches to it. If the executable or profile
  changes, CODESYS is restarted.
- A request that fails leaves no unsaved changes behind: the project is closed without saving,
  just as a failed one-shot run would.
- A request that times out (`TimeoutSeconds`) kills the session; the next call starts a new one.
- `SessionIdleMinutes` > 0 stops CODESYS after that many minutes without calls.
- With [Max projects](/CodesysMcpNet/guides/multiple-projects/) above 1, every configured
  project gets its own session (its own CODESYS instance), started, stopped and shown
  separately.

:::caution[The project is locked while the session runs]
While the session runs, CODESYS holds the project open, so opening it in the CODESYS IDE at the
same time is not supported. Click **Stop** on the settings page (or `POST /session/stop`) to
release the file; the next call starts the session again.
:::

Set `KeepSessionAlive` to `false` to start a separate CODESYS for every call instead. That's
slower, but never keeps the project open.
