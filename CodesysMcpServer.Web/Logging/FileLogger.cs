using System.Text;

namespace CodesysMcpServer.Web.Logging;

internal sealed class FileLogger : ILogger
{
    private static readonly AsyncLocal<Scope?> CurrentScope = new();

    private readonly string _category;
    private readonly FileLoggerProvider _provider;

    public FileLogger(string category, FileLoggerProvider provider)
    {
        _category = category;
        _provider = provider;
    }

    public IDisposable BeginScope<TState>(TState state) where TState : notnull
    {
        var scope = new Scope(state.ToString(), CurrentScope.Value);
        CurrentScope.Value = scope;
        return scope;
    }

    public bool IsEnabled(LogLevel logLevel) => _provider.IsEnabled(logLevel);

    public void Log<TState>(
        LogLevel logLevel,
        EventId eventId,
        TState state,
        Exception? exception,
        Func<TState, Exception?, string> formatter)
    {
        if (!IsEnabled(logLevel))
            return;

        var message = formatter(state, exception);
        if (string.IsNullOrEmpty(message) && exception is null)
            return;

        var builder = new StringBuilder(256);
        builder.Append(DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss.fff zzz"));
        builder.Append(" [").Append(Level(logLevel)).Append("] ");
        builder.Append(_category);

        if (eventId.Id != 0)
            builder.Append('(').Append(eventId.Id).Append(')');

        var scopeText = FormatScopes();
        if (scopeText is not null)
            builder.Append(" {").Append(scopeText).Append('}');

        builder.Append(": ").Append(message);

        if (exception is not null)
            builder.AppendLine().Append(exception);

        builder.Append(Environment.NewLine);
        _provider.Enqueue(builder.ToString());
    }

    private static string? FormatScopes()
    {
        var scope = CurrentScope.Value;
        if (scope is null)
            return null;

        var parts = new List<string>();
        while (scope is not null)
        {
            if (!string.IsNullOrEmpty(scope.Text))
                parts.Add(scope.Text!);
            scope = scope.Parent;
        }

        parts.Reverse();
        return parts.Count == 0 ? null : string.Join(" => ", parts);
    }

    private static string Level(LogLevel level) => level switch
    {
        LogLevel.Trace => "TRC",
        LogLevel.Debug => "DBG",
        LogLevel.Information => "INF",
        LogLevel.Warning => "WRN",
        LogLevel.Error => "ERR",
        LogLevel.Critical => "CRT",
        _ => "NON",
    };

    private sealed class Scope : IDisposable
    {
        public Scope(string? text, Scope? parent)
        {
            Text = text;
            Parent = parent;
        }

        public string? Text { get; }

        public Scope? Parent { get; }

        public void Dispose() => CurrentScope.Value = Parent;
    }
}
