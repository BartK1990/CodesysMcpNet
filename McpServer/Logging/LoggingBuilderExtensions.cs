using Microsoft.Extensions.DependencyInjection.Extensions;

namespace McpServer.Logging;

public static class LoggingBuilderExtensions
{
    /// <summary>
    /// Adds the rolling file logger. Console logging is unaffected — every record goes to both sinks.
    /// </summary>
    public static ILoggingBuilder AddFile(this ILoggingBuilder builder, IConfiguration configuration)
    {
        builder.Services.Configure<FileLoggerOptions>(configuration);
        builder.Services.TryAddEnumerable(
            ServiceDescriptor.Singleton<ILoggerProvider, FileLoggerProvider>());
        return builder;
    }
}
