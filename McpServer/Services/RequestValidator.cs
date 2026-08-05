using System.ComponentModel.DataAnnotations;

namespace McpServer.Services;

/// <summary>DataAnnotations validation shared by every request DTO, regardless of transport.</summary>
public static class RequestValidator
{
    public static void Validate(object model)
    {
        var context = new ValidationContext(model);
        var results = new List<ValidationResult>();

        if (Validator.TryValidateObject(model, context, results, validateAllProperties: true))
            return;

        var errors = results
            .SelectMany(r => r.MemberNames.DefaultIfEmpty(string.Empty), (r, member) => (member, r.ErrorMessage))
            .GroupBy(x => string.IsNullOrEmpty(x.member) ? "request" : x.member)
            .ToDictionary(g => g.Key, g => g.Select(x => x.ErrorMessage ?? "Invalid value").ToArray());

        var message = string.Join(" ", errors.SelectMany(kv => kv.Value.Select(v => $"{kv.Key}: {v}")));
        throw new CodesysValidationException(message, errors);
    }
}
