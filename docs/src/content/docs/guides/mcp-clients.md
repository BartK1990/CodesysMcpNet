---
title: Connecting MCP clients
description: Use the server from Claude Code, OpenCode, Claude Desktop and other MCP clients.
---

The server is a native MCP server using the **Streamable HTTP** transport at:

```
http://127.0.0.1:5088/mcp
```

The server must be running before the client connects. Once connected, the client lists the
tools described in [MCP tools](/CodesysMcpNet/reference/mcp-tools/).

## Claude Code

```bash
claude mcp add --transport http codesys http://127.0.0.1:5088/mcp
```

Or, to share the entry with your team, add `.mcp.json` at the root of your repository:

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

Check the connection with `/mcp` inside Claude Code.

## OpenCode

In `opencode.json` / `opencode.jsonc`:

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

## Claude Desktop and other stdio-only clients

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
(*Settings → Developer → Edit Config*). The URL argument is optional and defaults to
`http://localhost:5088/mcp`.

:::note
The proxy needs the main server to be running — start `CodesysMcpServer.Web.exe` normally
(or as a [Windows service](/CodesysMcpNet/guides/windows-service/)) first.
:::

## Tips for working with an assistant

- Ask for the **structure** or a **search** first, so the assistant learns the names of your
  POUs and variables before editing.
- Ask it to **compile** after changes; the compile result includes the compiler messages when
  the CODESYS version exposes them.
- Keep the project under version control (e.g. CODESYS Git or exported PLCopenXML) so changes
  are easy to review.
- While the session runs, CODESYS holds the project open. **Stop** the session on the
  settings page before opening the project in the CODESYS IDE.
