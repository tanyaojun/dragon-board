// jev-bridge: QuantBoard 后端 → typesafe/jev 的唯一通道（REST 直调已证死锁，见 design.md §10）
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return Response.json({ ok: true, model: "typesafe/jev" });
    }
    if (request.method !== "POST" || url.pathname !== "/evaluate") {
      return Response.json({ ok: false, errorCode: "not_found" }, { status: 404 });
    }
    if (request.headers.get("x-bridge-token") !== env.BRIDGE_TOKEN) {
      return Response.json({ ok: false, errorCode: "denied" }, { status: 401 });
    }
    let payload;
    try {
      payload = (await request.json()).payload;
    } catch {
      return Response.json({ ok: false, errorCode: "bad_json" }, { status: 400 });
    }
    if (!payload || typeof payload !== "object" || !payload.state || !payload.questions) {
      return Response.json({ ok: false, errorCode: "bad_payload" }, { status: 400 });
    }
    const t0 = Date.now();
    try {
      const result = await env.AI.run("typesafe/jev", payload);
      return Response.json({ ok: true, latencyMs: Date.now() - t0, result });
    } catch (e) {
      return Response.json(
        { ok: false, errorCode: "model_error", errorDetail: String(e).slice(0, 500), latencyMs: Date.now() - t0 },
        { status: 502 }
      );
    }
  },
};
