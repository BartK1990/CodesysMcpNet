using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

namespace CodesysMcpServer.Web.Mcp;

/// <summary>
/// "--stdio-proxy &lt;url&gt;" mode: bridges an MCP client that only speaks stdio (e.g. Claude
/// Desktop's claude_desktop_config.json) to the already running server's Streamable HTTP
/// endpoint. No web host is started — messages are pumped verbatim in both directions, so
/// stdout must carry nothing but JSON-RPC; all logging goes to stderr.
/// </summary>
public static class StdioProxy
{
    public const string Flag = "--stdio-proxy";

    public static bool TryGetEndpoint(string[] args, out Uri endpoint)
    {
        endpoint = null!;
        var index = Array.FindIndex(args, a => string.Equals(a, Flag, StringComparison.OrdinalIgnoreCase));
        if (index < 0)
            return false;

        var url = index + 1 < args.Length ? args[index + 1] : "http://localhost:5088/mcp";
        endpoint = new Uri(url);
        return true;
    }

    public static async Task<int> RunAsync(Uri endpoint)
    {
        using var loggerFactory = LoggerFactory.Create(logging =>
        {
            logging.SetMinimumLevel(LogLevel.Warning);
            logging.AddConsole(options => options.LogToStandardErrorThreshold = LogLevel.Trace);
        });
        var log = loggerFactory.CreateLogger("StdioProxy");

        using var cts = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; cts.Cancel(); };

        try
        {
            await using var http = await new HttpClientTransport(new HttpClientTransportOptions
                {
                    Endpoint = endpoint,
                    TransportMode = HttpTransportMode.StreamableHttp,
                    Name = "CodesysHttp",
                }, loggerFactory)
                .ConnectAsync(cts.Token);

            await using var stdio = new StdioServerTransport("CodesysStdioProxy", loggerFactory);

            // Whichever side closes first (Claude exits, server goes away) ends the proxy.
            var toServer = PumpAsync(stdio, http, cts.Token);
            var toClient = PumpAsync(http, stdio, cts.Token);
            await Task.WhenAny(toServer, toClient);
            cts.Cancel();

            return 0;
        }
        catch (OperationCanceledException) when (cts.IsCancellationRequested)
        {
            return 0;
        }
        catch (Exception ex)
        {
            log.LogError(ex, "stdio proxy to {Endpoint} failed", endpoint);
            return 1;
        }
    }

    private static async Task PumpAsync(ITransport from, ITransport to, CancellationToken ct)
    {
        try
        {
            await foreach (var message in from.MessageReader.ReadAllAsync(ct))
                await to.SendMessageAsync(message, ct);
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
        }
    }
}
