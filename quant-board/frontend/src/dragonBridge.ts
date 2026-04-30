import type { RuntimeBridgeRequest } from "./types";

interface BridgeMessage {
  type: string;
  requestId: string;
  ok?: boolean;
  payload?: unknown;
  error?: string;
}

function normalizeOrigin(url: string): string {
  return new URL(url).origin;
}

function createBridgeFrame(url: string, requestId: string): HTMLIFrameElement {
  const frame = document.createElement("iframe");
  frame.title = "DragonBoard QuantBoard Bridge";
  frame.dataset.quantBoardBridgeRequest = requestId;
  frame.src = url;
  frame.style.position = "fixed";
  frame.style.right = "0";
  frame.style.bottom = "0";
  frame.style.width = "1px";
  frame.style.height = "1px";
  frame.style.opacity = "0";
  frame.style.pointerEvents = "none";
  frame.style.border = "0";
  frame.style.zIndex = "-1";
  frame.setAttribute("aria-hidden", "true");
  document.body.appendChild(frame);
  return frame;
}

function requestDragonBoardBridge(request: RuntimeBridgeRequest, messageType: string): Promise<unknown> {
  const requestId = `qb_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const targetOrigin = normalizeOrigin(request.dragonBoardUrl);
  const timeoutMs = request.timeoutMs || 30000;
  let bridgeFrame: HTMLIFrameElement | null = null;
  let retryTimer = 0;

  return new Promise((resolve, reject) => {
    const cleanup = () => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(timer);
      window.clearInterval(retryTimer);
      if (bridgeFrame?.parentElement) {
        bridgeFrame.parentElement.removeChild(bridgeFrame);
      }
      bridgeFrame = null;
    };

    const fail = (message: string) => {
      cleanup();
      reject(new Error(message));
    };

    const sendRequest = () => {
      const bridgeWindow = bridgeFrame?.contentWindow;
      if (!bridgeWindow) {
        return;
      }
      try {
        bridgeWindow.postMessage(
          {
            ...request,
            type: messageType,
            requestId,
          },
          targetOrigin
        );
      } catch {
        // The hidden frame may still be on about:blank. The interval will retry after load.
      }
    };

    const onMessage = (event: MessageEvent<BridgeMessage>) => {
      if (event.origin !== targetOrigin) {
        return;
      }
      const data = event.data;
      if (!data || data.type !== "quant-board:indexeddb-result" || data.requestId !== requestId) {
        return;
      }
      cleanup();
      if (!data.ok) {
        reject(new Error(data.error || "DragonBoard IndexedDB bridge failed"));
        return;
      }
      resolve(data.payload);
    };

    const timer = window.setTimeout(() => {
      fail("等待 DragonBoard 页面响应超时。请确认 DragonBoard 已刷新到包含 QuantBoard bridge 的最新代码，并且 localhost:5173 可以正常访问。");
    }, timeoutMs);

    window.addEventListener("message", onMessage);
    bridgeFrame = createBridgeFrame(request.dragonBoardUrl, requestId);
    bridgeFrame.addEventListener("load", sendRequest);
    retryTimer = window.setInterval(sendRequest, 600);
    sendRequest();
  });
}

export function readDragonBoardIndexedDb(request: RuntimeBridgeRequest): Promise<unknown> {
  return requestDragonBoardBridge(request, "quant-board:read-indexeddb");
}
