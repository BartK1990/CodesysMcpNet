---
title: System Events
description: Read and set the handlers of Task Configuration > System Events.
---

System Events call a function when the runtime reaches a point in the application's life:
before it starts (`PrepareStart`), after it stops (`StopDone`), on an exception
(`Exception`), before a download or online change, and so on. In the IDE they live under
*Task Configuration → System Events*.

## Reading

`task_config` (`GET /tasks`) returns, for each task configuration:

- `systemEvents`: the configured handlers, each with `event`, `function`, `active`,
  `parameterType` (the event's parameter struct) and `description`;
- `availableSystemEvents`: every event the target's device description offers, with its
  description and parameter type.

## Adding, changing and removing a handler

`system_event_update` (`POST /tasks/system-events`) changes one event and saves the project.

| Argument | Meaning |
|---|---|
| `event` | Event name from `availableSystemEvents`, case-insensitive. |
| `function` | Function the event calls. Required to add a handler; omit it to keep the current one. |
| `active` | Enable or disable the handler. A new handler is enabled. |
| `remove` | Remove the handler. The function is kept. |
| `createFunction` | Create the function when it is missing (default `true`). |
| `parentPath` | Folder for a created function; defaults to the application. |
| `application` | Which application's Task Configuration, when the project has several. |

It behaves like the IDE's *Add Event Handler*:

- A missing function is created with the interface the IDE generates:

  ```text
  FUNCTION OnStopDone : DWORD
  VAR_IN_OUT
      EventPrm: CmpApp.EVTPARAM_CmpAppStop;
  END_VAR
  ```

  Fill in its body afterwards with `pou_update`.
- An existing function must be a FUNCTION. One that does not declare the event's parameter
  struct is accepted but reported in `warnings`; a `POINTER TO` the struct does not compile.
- The libraries the target needs for System Events (CmpApp, CmpIecTask, CmpEventMgr, Component
  Manager, ...) are added to the application when missing and listed in `librariesAdded`.
- An event has at most one handler: calling it again for a configured event changes the
  function or `active`, it never adds a second handler.

The response lists `action` (`added`, `updated` or `removed`), `functionCreated`,
`librariesAdded`, `warnings` and the resulting `systemEvents`.

## Limits

The CODESYS Scripting Engine has no API for System Events. The server uses the task
configuration's internal object model instead, the same one the IDE's editor uses. This was
verified with CODESYS 3.5 SP21 Patch 3. If a CODESYS version does not have that model,
`task_config` reports `systemEventsError` instead of the two lists and `system_event_update`
fails without changing the project.
