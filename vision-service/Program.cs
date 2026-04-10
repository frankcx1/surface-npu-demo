// Vision Service — Phi Silica Vision microservice for Field Inspection Copilot
// Wraps Windows App SDK ImageDescriptionGenerator on localhost:5100
// Flask app POSTs images here for on-device classification via NPU

using System.Text.Json;
using Microsoft.AspNetCore.Http.Features;

var builder = WebApplication.CreateBuilder(args);

// Allow large image uploads (16 MB)
builder.Services.Configure<FormOptions>(options =>
{
    options.MultipartBodyLengthLimit = 16 * 1024 * 1024;
});

builder.WebHost.UseUrls("http://localhost:5100");

var app = builder.Build();

// --- Health check ---
app.MapGet("/health", () =>
{
    return Results.Ok(new
    {
        status = "ok",
        service = "vision-service",
        runtime = "Phi Silica Vision (Windows App SDK)",
        phi_silica_available = VisionClassifier.IsAvailable,
        writing_assistant_available = TextRewriterService.IsAvailable
    });
});

// --- Describe image (general description) ---
app.MapPost("/describe", async (HttpRequest request) =>
{
    if (!VisionClassifier.IsAvailable)
        return Results.Json(new { error = "Phi Silica Vision not available on this device" }, statusCode: 503);

    var form = await request.ReadFormAsync();
    var file = form.Files.GetFile("image");
    if (file == null)
        return Results.BadRequest(new { error = "No 'image' file in request" });

    var kindStr = form.ContainsKey("kind") ? form["kind"].ToString() : "detailed";

    using var stream = file.OpenReadStream();
    using var ms = new MemoryStream();
    await stream.CopyToAsync(ms);
    var imageBytes = ms.ToArray();

    var result = await VisionClassifier.DescribeAsync(imageBytes, kindStr);
    return Results.Json(result);
});

// --- Classify image (constrained inspection categories) ---
app.MapPost("/classify", async (HttpRequest request) =>
{
    if (!VisionClassifier.IsAvailable)
        return Results.Json(new { error = "Phi Silica Vision not available on this device" }, statusCode: 503);

    var form = await request.ReadFormAsync();
    var file = form.Files.GetFile("image");
    if (file == null)
        return Results.BadRequest(new { error = "No 'image' file in request" });

    using var stream = file.OpenReadStream();
    using var ms = new MemoryStream();
    await stream.CopyToAsync(ms);
    var imageBytes = ms.ToArray();

    var result = await VisionClassifier.ClassifyAsync(imageBytes);
    return Results.Json(result);
});

// --- Rewrite text with Writing Assistant (Phi Silica TextRewriter on NPU) ---
app.MapPost("/rewrite", async (HttpRequest request) =>
{
    if (!TextRewriterService.IsAvailable)
        return Results.Json(new { error = "TextRewriter (Writing Assistant) not available on this device" }, statusCode: 503);

    var body = await request.ReadFromJsonAsync<RewriteRequest>();
    if (body == null || string.IsNullOrWhiteSpace(body.Text))
        return Results.BadRequest(new { error = "No 'text' field in request" });

    var result = await TextRewriterService.RewriteAsync(body.Text, body.Tone ?? body.Instruction);
    return Results.Json(result);
});

// --- Extract handwritten text from ink overlay ---
app.MapPost("/extract-text", async (HttpRequest request) =>
{
    if (!VisionClassifier.IsAvailable)
        return Results.Json(new { error = "Phi Silica Vision not available on this device" }, statusCode: 503);

    var form = await request.ReadFormAsync();
    var file = form.Files.GetFile("image");
    if (file == null)
        return Results.BadRequest(new { error = "No 'image' file in request" });

    using var stream = file.OpenReadStream();
    using var ms = new MemoryStream();
    await stream.CopyToAsync(ms);
    var imageBytes = ms.ToArray();

    var result = await VisionClassifier.ExtractTextAsync(imageBytes);
    return Results.Json(result);
});

// Initialize Phi Silica on startup
await VisionClassifier.InitializeAsync();
await TextRewriterService.InitializeAsync();

Console.WriteLine("==============================================");
Console.WriteLine("Vision Service (Phi Silica on NPU)");
Console.WriteLine($"  Phi Silica Vision:   {VisionClassifier.IsAvailable}");
Console.WriteLine($"  Writing Assistant:   {TextRewriterService.IsAvailable}");
Console.WriteLine("  Endpoints: /health, /describe, /classify, /extract-text, /rewrite");
Console.WriteLine("  Listening on http://localhost:5100");
Console.WriteLine("==============================================");

app.Run();

// Request model for /rewrite endpoint
public record RewriteRequest
{
    public string? Text { get; init; }
    public string? Tone { get; init; }
    public string? Instruction { get; init; }
}
