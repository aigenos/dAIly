# dAIly subscribe endpoint (Resend)

A ~60-line [Cloudflare Worker](./worker.js) that captures newsletter signups from
the landing-page form into your **Resend Audience**. Owner and subscribers then
receive the *identical* newsletter, because both go out through Resend — the
owner via a direct send, subscribers via a Broadcast to this audience.

Resend has no hosted signup form, so this tiny endpoint is the glue. It keeps
your Resend API key server-side (a Worker secret) — the static site never sees it.

## One-time setup

1. **Create an Audience** in Resend → *Audiences* → *New*. Copy its ID.
2. **Deploy the Worker** (free tier is plenty):
   ```bash
   cd subscribe
   npm i -g wrangler                      # once
   # put your audience id in wrangler.toml [vars], then:
   wrangler secret put RESEND_API_KEY     # paste your Resend key
   wrangler deploy                        # prints the https://…workers.dev URL
   ```
3. **Point the site at it.** Set the repo **Variable** `SUBSCRIBE_FORM_ACTION`
   to the Worker URL. The landing page's subscribe box now posts real signups.
4. **Send to that audience.** Set the repo **Variable** `RESEND_AUDIENCE_ID` to
   the same audience ID so the daily run Broadcasts the issue to subscribers.

That's it — subscribe, unsubscribe (managed by Resend), and delivery all work.

## How the pieces fit

| Concern      | Handled by                                                        |
|--------------|-------------------------------------------------------------------|
| Subscribe    | landing-page form → this Worker → Resend `add contact`            |
| Delivery     | `src/broadcast.py` → Resend Broadcast to `RESEND_AUDIENCE_ID`     |
| Unsubscribe  | Resend's managed `{{{RESEND_UNSUBSCRIBE_URL}}}` in every issue    |
| Feedback     | 😍 🙂 😕 mailto → `FEEDBACK_EMAIL` (defaults to the owner's inbox) |

## Don't want to run a Worker?

Any endpoint that accepts a POST with an `email` field and calls Resend's
[add-contact API](https://resend.com/docs/api-reference/contacts/create-contact)
works — a Vercel/Netlify function, Val Town, etc. Set `SUBSCRIBE_FORM_ACTION` to
its URL. Or skip capture entirely and add contacts manually in the Resend
dashboard; the daily Broadcast will still reach them.
