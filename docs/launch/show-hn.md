# Launch kit

Drafts for the launch posts, plus the pre-flight checklist. Edit the bracketed
bits, keep the first-person voice, never oversell.

---

## Show HN draft

**Title:**

> Show HN: dAIly – an open-source agent that reads AI news daily and tells me what to build

**Body:**

Live demo (today's real issue): https://aigenos.github.io/dAIly

I read AI news every morning and kept noticing the same failure: I'd finish 40
minutes of feeds and papers knowing *what happened*, but no closer to knowing
*what to build*. So I built an agent that does the reading and ends every
briefing with a concrete answer to that question.

Every day a GitHub Actions cron fetches frontier-lab blogs, AI-engineer
newsletters, r/LocalLLaMA, HN, arXiv, and Hugging Face Daily Papers, then an
LLM (Gemini, Claude, or local Ollama — pluggable) synthesizes a pyramid-shaped
briefing: a 90-second "Pulse" up top, then the part I actually built this for —
an **Opportunity of the Day**: a gap in the AI stack, why it's newly tractable
*this week*, what shape to build it as, and a first step for the next 7 days.
The rules I enforce in the prompt and post-processing: every claim needs a
linkable primary source, every opportunity needs at least two independent
signals, and no item appears twice.

It also keeps itself honest: every opportunity is logged to a public
receipts.md with date + issue link, so when one of them ships as a real product
later, the "called it" is on the record. [N] entries so far.

Things I'm unreasonably fond of:

- It runs entirely on GitHub Actions free tier + Gemini/Resend free tiers — no
  servers, ~$0/month.
- `SOURCE_PRESET=security` (or biotech, fintech, or your own one-file preset)
  retargets the whole agent to a different field — same synthesis, different
  beat. I'd love to see someone run this for their niche.
- Dead-link checking, cross-day dedup, and private "secret sauce" sections that
  go to your email but are stripped from the public archive.

It's MIT licensed. The README has a 5-minute fork-and-run guide. I've been
dogfooding it daily — happy to answer anything about the prompt design, the
fail-open plumbing, or what the LLM still gets wrong (it used to report the
same model launch three times in one email; fixing that was half the work).

Repo: https://github.com/aigenos/dAIly

---

## r/LocalLLaMA variant

**Title:**

> I built an open-source daily AI briefing agent that runs 100% local with Ollama — and ends every issue with "here's what to build"

**Body:**

Live example issue: https://aigenos.github.io/dAIly

It fetches lab blogs, this sub, HN, arXiv, and HF Daily Papers on a cron, then
synthesizes a source-linked briefing. With `PROVIDER=ollama` the whole pipeline
runs locally for free (I test with qwen2.5:14b) — no API keys, `DRY_RUN=true`
writes the HTML so you can just open it in a browser.

The differentiator: each issue ends with an "Opportunity of the Day" — a gap in
the stack with evidence it's heating up (it has to cite two independent
signals, upvote/star counts included, or the prompt rejects it). All
opportunities get logged to a public receipts file so the agent's track record
is auditable.

One env var (`SOURCE_PRESET`) retargets it from AI to security/biotech/fintech
or your own field. MIT, fork-and-run in ~5 min: https://github.com/aigenos/dAIly

Curious what local models people find good enough for the synthesis step —
qwen2.5:14b is solid, llama3.1 8B is hit-and-miss on the link discipline.

---

## Tweet-length variant

> Built an open-source agent that reads all of AI daily (labs, arXiv, HF, HN)
> and emails me a 90-second briefing that ends with "here's what you should
> build" — with receipts logged publicly so it has to own its calls.
>
> Fork it, or retarget it to your field with one env var:
> https://github.com/aigenos/dAIly
>
> Live issue: https://aigenos.github.io/dAIly

---

## Pre-launch checklist

- [ ] **Screenshots fresh** — run the *Refresh README screenshots* workflow;
      confirm `docs/assets/hero-light.png` / `hero-dark.png` show the latest
      issue. Then upload `hero-light.png` as the repo **social preview**
      (Settings → General → Social preview) so the HN/Twitter link card shows
      the product, not a blank tile.
- [ ] **Live demo up** — GitHub Pages serving `docs/` (Settings → Pages →
      main → /docs); today's issue loads; index previews + feed.xml work.
- [ ] **Subscribe link live** — `SUBSCRIBE_URL` (and embed form if used) set
      and tested end-to-end with a real email address.
- [ ] **Unsubscribe wired** — `UNSUBSCRIBE_URL` set; send yourself an email
      and click it. No launch before this works.
- [ ] **receipts.md has ≥5 entries** — the "called it" log needs a track
      record before strangers see it.
- [ ] **Discussions enabled** — Settings → General → Features (repo_setup.sh
      reminds you).
- [ ] **Repo metadata** — `bash scripts/repo_setup.sh` ran (description +
      topics).
- [ ] **README sample opportunity** — swap the placeholder example for a real
      one from a recent issue in `docs/digests/`.
- [ ] **Fresh clone test** — fork-and-run instructions verified start to
      finish on a clean account, ideally by someone else.
- [ ] **Fill the [N]** in the Show HN draft with the real receipts count.
- [ ] **Timing** — post Tue–Thu, ~14:00–15:00 UTC; be available for the first
      3 hours of comments.
