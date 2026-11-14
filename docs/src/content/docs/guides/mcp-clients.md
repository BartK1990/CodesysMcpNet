---
title: Connecting MCP clients
description: Use the server from Claude Code (terminal and desktop app), OpenCode, Claude Desktop and other MCP clients.
---

The server is a native MCP server using the **Streamable HTTP** transport at:

```
http://127.0.0.1:5088/mcp
```

The server must be running before the client connects. Once connected, the client lists the
tools described in [MCP tools](/CodesysMcpNet/reference/mcp-tools/).

:::tip[Before you connect]
1. Start `CodesysMcpServer.Web.exe` (or the [Windows service](/CodesysMcpNet/guides/windows-service/)).
2. Open `http://127.0.0.1:5088/` and check that the CODESYS path and project are set
   (see [First run](/CodesysMcpNet/getting-started/first-run/)).
3. If you changed the port in the [configuration](/CodesysMcpNet/reference/configuration/),
   use your port instead of `5088` in every example below.
:::

## Claude Code

Claude Code connects to the HTTP endpoint directly — no proxy needed. The terminal (CLI) and
the desktop app share the same MCP configuration, so a server you add in one is available in
the other.

### Terminal (CLI)

1. Open a terminal and add the server:

   ```bash
   claude mcp add --transport http --scope user codesys http://127.0.0.1:5088/mcp
   ```

   The `--scope` decides where the entry is stored:

   | Scope | Available in | Stored in |
   | --- | --- | --- |
   | `local` (default) | Only the folder you ran the command in | `~/.claude.json`, under that folder |
   | `user` | Every folder on this machine | `~/.claude.json` |
   | `project` | Everyone who clones the repository | `.mcp.json` at the repository root |

2. Check that it is registered:

   ```bash
   claude mcp list
   ```

   `codesys` should be listed as **connected**. If it shows *failed*, the server is not running
   or the URL/port is wrong.

3. Start Claude Code (`claude`) and type `/mcp` to see the server and its tools. Then just ask,
   for example: *"Show me the structure of the CODESYS project"*.

To remove the entry again: `claude mcp remove codesys`.

#### Sharing the entry with your team

Instead of `--scope project`, you can write `.mcp.json` at the root of your repository by
hand and commit it:

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

Claude Code asks each user to approve project-scoped servers the first time it sees them.

### Desktop app

The **Code** tab of the Claude desktop app (Windows / macOS) runs Claude Code and reads the
same configuration as the CLI:

- A server added with `claude mcp add --scope user …` (see above) is available in every
  session of the desktop app.
- A `.mcp.json` in the folder you open in the Code tab is picked up for that folder.

If you don't have the CLI installed, create `.mcp.json` (the example above) in the folder you
open in the Code tab. Start a session and type `/mcp` to verify that `codesys` is connected.

:::note
The **Chat** side of the Claude desktop app (not the Code tab) is configured separately — see
[Claude Desktop (chat)](#claude-desktop-chat-and-other-stdio-only-clients) below.
:::

### Long-running calls

Compiling a large project can take a while. If Claude Code reports a timeout on a tool call,
raise its MCP tool timeout (in milliseconds) before starting it, e.g. in PowerShell:

```powershell
$env:MCP_TOOL_TIMEOUT = "600000"
claude
```

## OpenCode

OpenCode connects to the HTTP endpoint directly. Although the server runs on your own machine,
configure it as a **remote** MCP server (`"type": "remote"`): in OpenCode, `"local"` means a
process that OpenCode starts itself and talks to over stdio, which is not how this server works.

The server must run on the same Windows host as OpenCode (it listens on `127.0.0.1` only).

1. Add the server to an OpenCode config file:

   - **Global** (every project): `~/.config/opencode/opencode.json`
     (on Windows `%USERPROFILE%\.config\opencode\opencode.json`, e.g.
     `C:\Users\<you>\.config\opencode\opencode.json`)
   - **Per project**: `opencode.json` or `opencode.jsonc` at the root of the project

   The entry goes under the top-level `mcp` key, inside its `servers` object, named `codesys`:

   ```jsonc
   {
     "$schema": "https://opencode.ai/config.json",
     "mcp": {
       "servers": {
         "codesys": {
           "type": "remote",
           "url": "http://127.0.0.1:5088/mcp"
         }
       }
     }
   }
   ```

   If the file already exists, do not replace it: merge the entry in. Keep your other
   top-level keys as they are, add `"mcp"` if it is missing, add `"servers"` inside it if it is
   missing, and put `"codesys"` next to any servers already listed there:

   ```jsonc
   {
     "$schema": "https://opencode.ai/config.json",
     "model": "…",                     // your existing settings stay untouched
     "mcp": {
       "servers": {
         "some-other-server": { … },   // existing servers stay as they are
         "codesys": {                  // ← add this entry
           "type": "remote",
           "url": "http://127.0.0.1:5088/mcp"
         }
       }
     }
   }
   ```

   Alternatively, add it from the command line without editing the file:

   ```bash
   opencode mcp add codesys --global --url http://127.0.0.1:5088/mcp
   ```

   Leave out `--global` to add it to the current project's config instead.

2. Check that it is connected (the server must already be running):

   ```bash
   opencode mcp list
   ```

   `codesys` should be listed as *connected*. OpenCode reloads its configuration when the file
   changes, so a restart is not needed after editing it.

3. Start `opencode` in your project folder and ask, for example: *"Use the codesys tools to
   compile the project"*. The tools appear prefixed with the server name (`codesys_…`).

To switch the server off temporarily without deleting the entry, add `"disabled": true` to it.

:::note[Older OpenCode config format]
Earlier OpenCode versions put server entries directly under `mcp` (no `servers` object) and
used `"enabled": false` to switch one off:

```jsonc
{
  "mcp": {
    "codesys": { "type": "remote", "url": "http://127.0.0.1:5088/mcp", "enabled": true }
  }
}
```

OpenCode still reads this format for compatibility, but use `mcp.servers` for new configs.
:::

## Claude Desktop (chat) and other stdio-only clients

Clients that can only launch an MCP server as a process (stdio) can use the executable's
built-in **stdio proxy**. It starts no web server; it just forwards messages to the server that
is already running:

```json
{
  "mcpServers": {
    "codesys": {
      "command": "C:\\Tools\\CodesysMcpServer\\CodesysMcpServer.Web.exe",
      "args": ["--stdio-proxy", "http://127.0.0.1:5088/mcp"]
    }
  }
}
```

For Claude Desktop this goes into `claude_desktop_config.json`
(*Settings → Developer → Edit Config*); restart Claude Desktop afterwards. The URL argument is
optional and defaults to `http://localhost:5088/mcp`.

:::note
The proxy needs the main server to be running — start `CodesysMcpServer.Web.exe` normally
(or as a [Windows service](/CodesysMcpNet/guides/windows-service/)) first.
:::

## Troubleshooting the connection

- **Not connected / failed** — open `http://127.0.0.1:5088/` in a browser. If the settings
  page doesn't load, the server isn't running or listens on another port.
- **Client runs in WSL or a container** — `127.0.0.1` there is not the Windows host. Use the
  Windows host's address (or WSL's mirrored networking) and make sure the server listens on
  that address.
- **Tools are listed but every call fails** — check the session state on the settings page;
  see [Troubleshooting](/CodesysMcpNet/reference/troubleshooting/).

## Tips for working with an assistant

- Ask for the **structure** or a **search** first, so the assistant learns the names of your
  POUs and variables before editing.
- Ask it to **compile** after changes; the compile result includes the compiler messages when
  the CODESYS version exposes them.
- Keep the project under version control (e.g. CODESYS Git or exported PLCopenXML) so changes
  are easy to review.
- While the session runs, CODESYS holds the project open. **Stop** the session on the
  settings page before opening the project in the CODESYS IDE.
