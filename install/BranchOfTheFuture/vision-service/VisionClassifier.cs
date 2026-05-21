// VisionClassifier — wraps Phi Silica ImageDescriptionGenerator
// Provides describe, classify, and extract-text operations

using System.Text.Json;
using System.Text.RegularExpressions;
using System.Runtime.InteropServices.WindowsRuntime;

#if WINDOWS
using Microsoft.Graphics.Imaging;
using Microsoft.Windows.AI;
using Microsoft.Windows.AI.ContentSafety;
using Microsoft.Windows.AI.Imaging;
using Windows.Graphics.Imaging;
using Windows.Storage.Streams;
#endif

public static class VisionClassifier
{
    public static bool IsAvailable { get; private set; } = false;

    // Constrained categories for field inspection (matches build spec)
    private static readonly string[] InspectionCategories = new[]
    {
        "Water Damage",
        "Structural Crack",
        "Mold",
        "Electrical Hazard",
        "Trip Hazard"
    };

    // LAF token — unlocks Phi Silica APIs for packaged apps
    // PFN: Microsoft.NPUDemo.VisionService_r0xr04974zwaa
    private const string LafFeatureId = "com.microsoft.windows.ai.languagemodel";
    private const string LafToken = "1A1xXf+TQb5ETXD4dqSOJA==";
    // Attestation uses the actual publisher ID hash from the installed MSIX
    private const string LafAttestation =
        "r0xr04974zwaa has registered their use of " +
        "com.microsoft.windows.ai.languagemodel with Microsoft " +
        "and agrees to the terms of use.";

#if WINDOWS
    private static ImageDescriptionGenerator? _generator;
#endif

    private static readonly string LogPath = @"C:\temp\vision-service-init.log";

    private static void Log(string msg)
    {
        var line = $"[{DateTime.Now:HH:mm:ss.fff}] {msg}";
        Console.WriteLine(line);
        try { File.AppendAllText(LogPath, line + Environment.NewLine); } catch { }
    }

    public static async Task InitializeAsync()
    {
#if WINDOWS
        try
        {
            Log($"Init starting. Log file: {LogPath}");

            // Unlock Phi Silica via LAF token (required for packaged apps)
            try
            {
                var access = Windows.ApplicationModel.LimitedAccessFeatures
                    .TryUnlockFeature(LafFeatureId, LafToken, LafAttestation);
                Log($"[VisionClassifier] LAF unlock status: {access.Status}");
                if (access.Status != Windows.ApplicationModel.LimitedAccessFeatureStatus.Available &&
                    access.Status != Windows.ApplicationModel.LimitedAccessFeatureStatus.AvailableWithoutToken)
                {
                    Log($"[VisionClassifier] LAF token not accepted (status: {access.Status})");
                    Log("[VisionClassifier] Continuing anyway — API may still work on experimental channel");
                }
            }
            catch (Exception lafEx)
            {
                Log($"[VisionClassifier] LAF unlock failed: {lafEx.Message}");
                Log("[VisionClassifier] Continuing — may work without token on experimental channel");
            }

            // Check if ImageDescriptionGenerator is available on this device
            var readyState = ImageDescriptionGenerator.GetReadyState();
            Log($"[VisionClassifier] GetReadyState: {readyState}");
            if (readyState == AIFeatureReadyState.NotReady)
            {
                Log("[VisionClassifier] Model not ready, calling EnsureReadyAsync...");
                var deployResult = await ImageDescriptionGenerator.EnsureReadyAsync();
                Log($"[VisionClassifier] EnsureReadyAsync completed (Status: {deployResult.Status})");
                if (deployResult.Status != AIFeatureReadyResultState.Success)
                {
                    Log($"[VisionClassifier] EnsureReadyAsync failed: {deployResult.ExtendedError?.Message}");
                    IsAvailable = false;
                    return;
                }
            }
            else if (readyState == AIFeatureReadyState.NotSupportedOnCurrentSystem)
            {
                Log("[VisionClassifier] Not supported on this system");
                IsAvailable = false;
                return;
            }
            else if (readyState == AIFeatureReadyState.DisabledByUser)
            {
                Log("[VisionClassifier] AI features disabled by user in Windows Settings");
                IsAvailable = false;
                return;
            }

            _generator = await ImageDescriptionGenerator.CreateAsync();
            IsAvailable = true;
            Log("[VisionClassifier] Phi Silica Vision initialized successfully");
        }
        catch (Exception ex)
        {
            Log($"[VisionClassifier] Initialization failed: {ex.Message}");
            Log($"[VisionClassifier] Exception type: {ex.GetType().FullName}");
            Log($"[VisionClassifier] Stack trace: {ex.StackTrace}");
            IsAvailable = false;
        }
#else
        Console.WriteLine("[VisionClassifier] Not running on Windows — Phi Silica unavailable");
        IsAvailable = false;
        await Task.CompletedTask;
#endif
    }

    /// <summary>
    /// General image description using Phi Silica Vision.
    /// </summary>
    public static async Task<object> DescribeAsync(byte[] imageBytes, string kind = "detailed")
    {
#if WINDOWS
        if (_generator == null)
            return new { error = "Vision model not initialized" };

        try
        {
            var imageBuffer = await BytesToImageBuffer(imageBytes);

            var descKind = kind.ToLower() switch
            {
                "caption" => ImageDescriptionKind.BriefDescription,
                "detailed" => ImageDescriptionKind.DetailedDescription,
                "accessibility" => ImageDescriptionKind.AccessibleDescription,
                _ => ImageDescriptionKind.DetailedDescription
            };

            var result = await _generator.DescribeAsync(imageBuffer, descKind, new ContentFilterOptions());
            var description = result.Description ?? "";

            return new
            {
                description = description,
                kind = kind,
                status = "complete"
            };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
#else
        await Task.CompletedTask;
        return new { error = "Phi Silica not available on this platform" };
#endif
    }

    /// <summary>
    /// Classify an image into constrained inspection categories.
    /// Uses Phi Silica detailed description, then maps to categories + severity.
    /// </summary>
    public static async Task<object> ClassifyAsync(byte[] imageBytes)
    {
#if WINDOWS
        if (_generator == null)
            return new { error = "Vision model not initialized" };

        try
        {
            var imageBuffer = await BytesToImageBuffer(imageBytes);

            // Get a detailed description from Phi Silica
            var descResult = await _generator.DescribeAsync(
                imageBuffer,
                ImageDescriptionKind.DetailedDescription,
                new ContentFilterOptions()
            );
            var description = descResult.Description ?? "";

            // Map description to constrained category + severity + confidence
            var classification = MapToInspectionCategory(description);

            return new
            {
                category = classification.Category,
                severity = classification.Severity,
                confidence = classification.Confidence,
                explanation = classification.Explanation,
                raw_description = description,
                status = "complete"
            };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
#else
        await Task.CompletedTask;
        return new { error = "Phi Silica not available on this platform" };
#endif
    }

    /// <summary>
    /// Extract handwritten text from an ink overlay image.
    /// </summary>
    public static async Task<object> ExtractTextAsync(byte[] imageBytes)
    {
#if WINDOWS
        if (_generator == null)
            return new { error = "Vision model not initialized" };

        try
        {
            var imageBuffer = await BytesToImageBuffer(imageBytes);

            // Use detailed description to capture any text in the image
            var textResult = await _generator.DescribeAsync(
                imageBuffer,
                ImageDescriptionKind.DetailedDescription,
                new ContentFilterOptions()
            );

            return new
            {
                extracted_text = textResult.Description ?? "",
                status = "complete"
            };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
#else
        await Task.CompletedTask;
        return new { error = "Phi Silica not available on this platform" };
#endif
    }

#if WINDOWS
    /// <summary>
    /// Convert raw image bytes to ImageBuffer via SoftwareBitmap.
    /// </summary>
    private static async Task<ImageBuffer> BytesToImageBuffer(byte[] imageBytes)
    {
        using var memStream = new InMemoryRandomAccessStream();
        await memStream.WriteAsync(imageBytes.AsBuffer());
        memStream.Seek(0);

        var decoder = await BitmapDecoder.CreateAsync(memStream);
        var softwareBitmap = await decoder.GetSoftwareBitmapAsync(
            BitmapPixelFormat.Bgra8,
            BitmapAlphaMode.Premultiplied
        );

        return ImageBuffer.CreateForSoftwareBitmap(softwareBitmap);
    }
#endif

    /// <summary>
    /// Map a free-text image description to constrained inspection categories.
    /// Uses keyword matching against the Phi Silica description to produce
    /// a structured classification with category, severity, and confidence.
    /// </summary>
    private static InspectionClassification MapToInspectionCategory(string description)
    {
        var lower = description.ToLower();

        // Score each category based on keyword presence
        var scores = new Dictionary<string, int>
        {
            ["Water Damage"] = ScoreKeywords(lower,
                "water", "moisture", "wet", "damp", "leak", "drip", "stain",
                "discoloration", "puddle", "flood", "seepage", "condensation",
                "water damage", "water stain", "pipe"),
            ["Structural Crack"] = ScoreKeywords(lower,
                "crack", "fracture", "split", "gap", "separation", "broken",
                "structural", "foundation", "wall crack", "concrete", "fissure",
                "settlement", "shift"),
            ["Mold"] = ScoreKeywords(lower,
                "mold", "mould", "fungus", "fungi", "spore", "mildew",
                "black spot", "growth", "organic", "damp growth", "discolored patch"),
            ["Electrical Hazard"] = ScoreKeywords(lower,
                "wire", "wiring", "electrical", "spark", "outlet", "exposed wire",
                "cable", "panel", "circuit", "burn mark", "scorch", "socket",
                "voltage", "power"),
            ["Trip Hazard"] = ScoreKeywords(lower,
                "trip", "uneven", "raised", "loose", "broken tile", "carpet",
                "threshold", "step", "obstacle", "floor", "surface", "tripping",
                "gap", "hole", "damaged floor")
        };

        // Find best match
        var bestCategory = "Water Damage"; // default
        var bestScore = 0;
        foreach (var kvp in scores)
        {
            if (kvp.Value > bestScore)
            {
                bestScore = kvp.Value;
                bestCategory = kvp.Key;
            }
        }

        // Derive confidence from score strength (0-100)
        var confidence = bestScore switch
        {
            >= 5 => Math.Min(95, 70 + bestScore * 3),
            >= 3 => 65 + bestScore * 3,
            >= 1 => 50 + bestScore * 10,
            _ => 40 // no keywords matched — low confidence
        };

        // Derive severity from confidence + category risk weight
        var severity = (bestCategory, confidence) switch
        {
            ("Electrical Hazard", >= 70) => "Critical",
            ("Electrical Hazard", _) => "High",
            ("Structural Crack", >= 80) => "High",
            ("Mold", >= 80) => "High",
            (_, >= 85) => "High",
            (_, >= 65) => "Moderate",
            _ => "Low"
        };

        // Build explanation from the description (first sentence or first 120 chars)
        var explanation = description.Length > 120
            ? description[..120].TrimEnd() + "..."
            : description;

        // Try to use just the first sentence
        var firstSentenceEnd = description.IndexOfAny(new[] { '.', '!', '?' });
        if (firstSentenceEnd > 0 && firstSentenceEnd < 150)
            explanation = description[..(firstSentenceEnd + 1)];

        return new InspectionClassification
        {
            Category = bestCategory,
            Severity = severity,
            Confidence = Math.Min(confidence, 100),
            Explanation = explanation
        };
    }

    private static int ScoreKeywords(string text, params string[] keywords)
    {
        int score = 0;
        foreach (var kw in keywords)
        {
            if (text.Contains(kw))
                score++;
        }
        return score;
    }
}

public record InspectionClassification
{
    public string Category { get; init; } = "";
    public string Severity { get; init; } = "";
    public int Confidence { get; init; }
    public string Explanation { get; init; } = "";
}
