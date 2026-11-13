using System.ComponentModel;
using System.ComponentModel.DataAnnotations;

namespace CodesysMcpServer.Web.Models;

/// <summary>
/// POST /tasks/system-events. Adds, changes or removes the handler of one System Event
/// (Task Configuration &gt; System Events), then saves the project.
/// </summary>
public sealed class SystemEventUpdateRequest
{
    [Required(AllowEmptyStrings = false)]
    [Description("System Event name as task_config lists it under availableSystemEvents, e.g. \"PrepareStart\", \"StopDone\", \"Exception\". Matched case-insensitively.")]
    public string Event { get; set; } = string.Empty;

    [Description("Function the event calls. Required to add a handler; to change an existing one, omit it to keep the current function.")]
    public string? Function { get; set; }

    [Description("Optional: enable (true) or disable (false) the handler. A new handler is enabled; an existing one keeps its state when omitted.")]
    public bool? Active { get; set; }

    [Description("Remove the event's handler instead. The function itself is kept.")]
    public bool Remove { get; set; }

    [Description("Create the function when it does not exist (default true), with the interface the IDE generates: FUNCTION <name> : DWORD with VAR_IN_OUT EventPrm: <the event's parameter struct>.")]
    public bool CreateFunction { get; set; } = true;

    [Description("Optional project-relative folder for a created function. Defaults to the application.")]
    public string? ParentPath { get; set; }

    [Description("Optional application (name or path) whose Task Configuration to change. Needed only when the project has several.")]
    public string? Application { get; set; }
}
