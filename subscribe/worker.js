/**
 * dAIly subscribe endpoint — a tiny Cloudflare Worker that captures newsletter
 * signups from the landing-page form into a Resend Audience.
 *
 * The static landing page (docs/index.html) posts a single `email` field here;
 * this Worker adds the contact to your Resend Audience so the daily Broadcast
 * reaches them. It NEVER exposes your Resend key — that lives as a Worker secret.
 *
 * Deploy (free tier is plenty):
 *   cd subscribe
 *   npm i -g wrangler                      # once
 *   wrangler secret put RESEND_API_KEY     # paste your Resend key
 *   wrangler deploy                        # prints https://<name>.<you>.workers.dev
 * Then set the repo Variable SUBSCRIBE_FORM_ACTION to that URL.
 *
 * Config (wrangler.toml [vars] or dashboard):
 *   RESEND_AUDIENCE_ID  — the audience to add contacts to (same one you send to)
 *   REDIRECT_URL        — optional; where to bounce the browser after signup
 *                         (e.g. https://you.github.io/dAIly/?subscribed=1)
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }
    if (request.method !== "POST") {
      return page("Send a POST with an email address to subscribe.", 405);
    }

    const email = (await readEmail(request)).trim().toLowerCase();
    if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      return page("That doesn't look like a valid email address.", 400);
    }
    if (!env.RESEND_API_KEY || !env.RESEND_AUDIENCE_ID) {
      return page("Subscribe is not configured yet. Please try again later.", 500);
    }

    let ok = false;
    try {
      const r = await fetch(
        `https://api.resend.com/audiences/${env.RESEND_AUDIENCE_ID}/contacts`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.RESEND_API_KEY}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ email, unsubscribed: false }),
        }
      );
      // 200/201 = created; 409 = already a contact → both count as success.
      ok = r.ok || r.status === 409;
    } catch (_) {
      ok = false;
    }

    if (!ok) {
      return page("Something went wrong subscribing you. Please try again.", 502);
    }
    // Native form posts land here in a popup; redirect back if configured.
    if (env.REDIRECT_URL) {
      return Response.redirect(env.REDIRECT_URL, 303);
    }
    return page("🎉 You're subscribed! Watch your inbox for the next dAIly.", 200);
  },
};

async function readEmail(request) {
  const ct = request.headers.get("content-type") || "";
  try {
    if (ct.includes("application/json")) {
      return String((await request.json()).email || "");
    }
    const form = await request.formData();
    return String(form.get("email") || "");
  } catch (_) {
    return "";
  }
}

function page(message, status) {
  const html = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>dAIly</title></head>
<body style="margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
background:#0a1429;color:#ececf5;display:flex;align-items:center;
justify-content:center;min-height:100vh;text-align:center;">
<div style="max-width:420px;padding:32px;">
<div style="font-size:26px;font-weight:800;margin-bottom:12px;">d<span style="color:#6ee7b7;">AI</span>ly</div>
<p style="font-size:16px;line-height:1.6;color:#c8c8d8;">${message}</p>
</div></body></html>`;
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", ...CORS },
  });
}
