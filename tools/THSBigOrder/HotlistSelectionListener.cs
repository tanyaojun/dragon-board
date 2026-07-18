using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace THSBigOrder
{
    internal sealed class HotlistSelectionListener : IDisposable
    {
        internal const int Port = 38891;
        private const string LocalhostOrigin = "http://localhost:5173";
        private const string LoopbackOrigin = "http://127.0.0.1:5173";
        private readonly Action<HotlistSelectionMessage> _onSelection;
        private readonly CancellationTokenSource _cancellation = new CancellationTokenSource();
        private HttpListener _listener;

        internal HotlistSelectionListener(Action<HotlistSelectionMessage> onSelection)
        {
            _onSelection = onSelection;
        }

        internal bool Start()
        {
            try
            {
                _listener = new HttpListener();
                _listener.Prefixes.Add(string.Format("http://127.0.0.1:{0}/", Port));
                _listener.Start();
                Task.Run(() => ListenAsync());
                return true;
            }
            catch
            {
                Dispose();
                return false;
            }
        }

        private async Task ListenAsync()
        {
            while (!_cancellation.IsCancellationRequested && _listener != null && _listener.IsListening)
            {
                HttpListenerContext context;
                try
                {
                    context = await _listener.GetContextAsync().ConfigureAwait(false);
                }
                catch
                {
                    break;
                }

                await HandleAsync(context).ConfigureAwait(false);
            }
        }

        private async Task HandleAsync(HttpListenerContext context)
        {
            var response = context.Response;
            var origin = context.Request.Headers["Origin"];
            if (!IsAllowedOrigin(origin))
            {
                response.StatusCode = 403;
                response.Close();
                return;
            }
            if (!string.IsNullOrEmpty(origin))
            {
                response.Headers["Access-Control-Allow-Origin"] = origin;
                response.Headers["Vary"] = "Origin";
            }
            response.Headers["Access-Control-Allow-Methods"] = "POST, OPTIONS";
            response.Headers["Access-Control-Allow-Headers"] = "Content-Type";

            if (context.Request.HttpMethod == "OPTIONS")
            {
                response.StatusCode = 204;
                response.Close();
                return;
            }

            if (context.Request.HttpMethod != "POST" ||
                !string.Equals(context.Request.Url.AbsolutePath, "/hotlist/selection", StringComparison.OrdinalIgnoreCase))
            {
                response.StatusCode = 404;
                response.Close();
                return;
            }

            string body;
            using (var reader = new StreamReader(context.Request.InputStream, new UTF8Encoding(false)))
            {
                body = await reader.ReadToEndAsync().ConfigureAwait(false);
            }

            HotlistSelectionMessage message;
            if (!HotlistSelectionMessage.TryParse(body, out message))
            {
                response.StatusCode = 400;
                response.Close();
                return;
            }

            _onSelection?.Invoke(message);
            response.StatusCode = 204;
            response.Close();
        }

        internal static bool IsAllowedOrigin(string origin)
        {
            return string.IsNullOrEmpty(origin) ||
                string.Equals(origin, LocalhostOrigin, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(origin, LoopbackOrigin, StringComparison.OrdinalIgnoreCase);
        }

        public void Dispose()
        {
            _cancellation.Cancel();
            if (_listener == null) return;
            try { _listener.Stop(); } catch { }
            _listener.Close();
            _listener = null;
        }
    }
}
