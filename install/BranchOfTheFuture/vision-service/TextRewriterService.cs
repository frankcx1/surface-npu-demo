// TextRewriterService — wraps Windows AI TextRewriter (Writing Assistant)
// Provides on-device text rewriting via Phi Silica on NPU

#if WINDOWS
using Microsoft.Windows.AI;
using Microsoft.Windows.AI.Text;
#endif

public static class TextRewriterService
{
    public static bool IsAvailable { get; private set; } = false;

#if WINDOWS
    private static LanguageModel? _languageModel;
    private static TextRewriter? _rewriter;
#endif

    private static void Log(string msg)
    {
        Console.WriteLine($"[{DateTime.Now:HH:mm:ss.fff}] [TextRewriter] {msg}");
    }

    public static async Task InitializeAsync()
    {
#if WINDOWS
        try
        {
            // LanguageModel shares the same LAF token already unlocked by VisionClassifier
            var readyState = LanguageModel.GetReadyState();
            Log($"LanguageModel GetReadyState: {readyState}");

            if (readyState == AIFeatureReadyState.NotReady)
            {
                Log("LanguageModel not ready, calling EnsureReadyAsync...");
                var result = await LanguageModel.EnsureReadyAsync();
                Log($"EnsureReadyAsync status: {result.Status}");
            }
            else if (readyState == AIFeatureReadyState.NotSupportedOnCurrentSystem)
            {
                Log("LanguageModel not supported on this system");
                IsAvailable = false;
                return;
            }

            _languageModel = await LanguageModel.CreateAsync();
            _rewriter = new TextRewriter(_languageModel);
            IsAvailable = true;
            Log("TextRewriter initialized successfully");
        }
        catch (Exception ex)
        {
            Log($"Initialization failed: {ex.Message}");
            IsAvailable = false;
        }
#else
        Console.WriteLine("[TextRewriter] Not running on Windows — unavailable");
        IsAvailable = false;
        await Task.CompletedTask;
#endif
    }

    /// <summary>
    /// Rewrite text using the Windows AI Writing Assistant on NPU.
    /// </summary>
    public static async Task<object> RewriteAsync(string text, string? tone = null)
    {
#if WINDOWS
        if (_rewriter == null)
            return new { error = "TextRewriter not initialized" };

        try
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();

            LanguageModelResponseResult result;

            if (!string.IsNullOrEmpty(tone))
            {
                // Try predefined tone first
                var parsedTone = tone.ToLower() switch
                {
                    "formal" => TextRewriteTone.Formal,
                    "casual" => TextRewriteTone.Casual,
                    "concise" => TextRewriteTone.Concise,
                    "general" => TextRewriteTone.General,
                    _ => (TextRewriteTone?)null
                };

                if (parsedTone.HasValue)
                {
                    result = await _rewriter.RewriteAsync(text, parsedTone.Value);
                }
                else
                {
                    // Custom tone string — use RewriteCustomAsync
                    result = await _rewriter.RewriteCustomAsync(text, tone);
                }
            }
            else
            {
                result = await _rewriter.RewriteAsync(text);
            }

            sw.Stop();
            var rewritten = result.Text ?? "";

            Log($"Rewrite completed in {sw.ElapsedMilliseconds}ms ({text.Length} chars -> {rewritten.Length} chars)");

            return new
            {
                rewritten = rewritten,
                tone = tone ?? "default",
                inference_time = Math.Round(sw.Elapsed.TotalSeconds, 1),
                model = "Phi Silica TextRewriter",
                source = "npu_writing_assistant",
                status = "complete"
            };
        }
        catch (Exception ex)
        {
            Log($"Rewrite failed: {ex.Message}");
            return new { error = ex.Message };
        }
#else
        await Task.CompletedTask;
        return new { error = "TextRewriter not available on this platform" };
#endif
    }
}
