# Launch kit

Drafts for the launch posts, plus the pre-flight runbook. Edit the bracketed
bits, keep the first-person voice, never oversell. **Nothing here is posted
automatically — every post is a deliberate human act, in the order below.**

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

Every day a GitHub Actions cron fetches frontier-lab blogs, the top AI
newsletters, r/LocalLLaMA, HN, arXiv, and Hugging Face Daily Papers, then an
LLM (Gemini, Claude, or local Ollama — pluggable) synthesizes a pyramid-shaped
briefing: image-rich Top Stories, a 90-second "Pulse", a standards-and-
protocols block for people building agent platforms (MCP / A2A / Agent Skills
updates never slip past it), and the part I actually built this for — an
**Opportunity of the Day**: a gap in the AI stack, why it's newly tractable
*this week*, what shape to build it as, and a first step for the next 7 days.
The rules I enforce in the prompt and post-processing: every claim needs a
linkable primary source, every opportunity needs at least two independent
signals, and no item appears twice — same day or across days.

It also keeps itself honest: every opportunity is logged to a public
receipts.md with date + issue link, so when one of them ships as a real
product later, the "called it" is on the record. 66 entries and counting.

Things I'm unreasonably fond of:

- It runs entirely on GitHub Actions free tier + Gemini/Resend free tiers — no
  servers, ~$0/month.
- Every issue is also a **podcast episode**: gTTS voices the core sections to
  an MP3, the email gets a ▶️ Listen button, and `podcast.xml` is subscribable
  in any podcast app. Still $0.
- `SOURCE_PRESET=security` (or biotech, fintech, or your own one-file preset)
  retargets the whole agent to a different field — same synthesis, different
  beat. I'd love to see someone run this for their niche.
- Subscribers get the *byte-identical* email I do (one renderer, one sender),
  with managed unsubscribe — plus dead-link checking, cross-day dedup, and
  private "secret sauce" sections that reach my inbox but are stripped from
  the public archive with a fail-closed leak check.

It's MIT licensed. The README has a 5-minute fork-and-run guide. I've been
dogfooding it daily for months — happy to answer anything about the prompt
design, the fail-open plumbing, or what the LLM still gets wrong (it used to
report the same model launch three times in one email; fixing that was half
the work).

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
is auditable. There's also a dedicated standards/protocols block so MCP, A2A,
and Agent Skills changes never get buried under model-release news.

Bonus: every issue doubles as a podcast episode (free gTTS → MP3 → RSS feed
with enclosures), so you can listen on a commute instead of reading.

One env var (`SOURCE_PRESET`) retargets it from AI to security/biotech/fintech
or your own field. MIT, fork-and-run in ~5 min: https://github.com/aigenos/dAIly

Curious what local models people find good enough for the synthesis step —
qwen2.5:14b is solid, llama3.1 8B is hit-and-miss on the link discipline.

---

## X thread variant (post as a 4-tweet thread)

**1/**
> I got tired of finishing 40 min of AI news knowing what HAPPENED but not
> what to BUILD.
>
> So I built dAIly: an open-source agent that reads everything (labs, arXiv,
> HF, HN, the top newsletters) and emails me a briefing that ends with
> "here's what to build today."

**2/**
> It keeps receipts. Every "Opportunity of the Day" is logged publicly with
> date + issue link — 66 calls on the record so far. When one ships as a real
> product, the "called it" is auditable.
>
> [attach: docs/assets/screenshot-email-dark.png]

**3/**
> The parts I like most:
> • ~$0/mo — GitHub Actions + free API tiers, no servers
> • every issue is also a podcast episode (auto-TTS → RSS)
> • a standards block so MCP / A2A / Agent Skills changes never slip past
> • SOURCE_PRESET=security retargets the whole agent to your field

**4/**
> MIT licensed, fork-and-run in 5 minutes.
>
> Live issue: https://aigenos.github.io/dAIly
> Repo: https://github.com/aigenos/dAIly

---

## Pre-launch runbook (in order — do not skip the soak)

### Phase 1 — Soak (3–4 days before launch)
- [ ] **Run 3–4 consecutive real issues** and read each critically. The
      coverage, pillar block, and theme changes are newer than the archive —
      the first thing every visitor opens is today's issue. Check: Standards
      block has real content (or an honest "no movement" line), no repeated
      stories across days, links resolve, ▶️ Listen plays.
- [ ] **Resend: Full-access API key** set as `RESEND_API_KEY`; **Resend
      Doctor** workflow all ✅.
- [ ] **End-to-end subscribe test** — subscribe with a second email address
      via the live site form; confirm (Buttondown double opt-in); verify the
      NEXT morning's issue arrives via Resend, identical to yours, and its
      unsubscribe link works. No launch before this works.

### Phase 2 — Polish (day before)
- [ ] **Social preview** — upload `docs/assets/screenshot-email-dark.png`
      as the repo social preview (Settings → General → Social preview) so the
      HN/X link card shows the product.
- [ ] **README sample opportunity** — swap the placeholder example for a real
      one from a recent issue in `docs/digests/`.
- [ ] **receipts count** — refresh the "66 entries" figure in the drafts
      above (`grep -c '^- \*\*' docs/receipts.md`).
- [ ] **Discussions enabled** — Settings → General → Features.
- [ ] **Repo metadata** — `bash scripts/repo_setup.sh` (description + topics).
- [ ] **Fresh clone test** — fork-and-run instructions verified start to
      finish on a clean account, ideally by someone else.

### Phase 3 — Launch day
- [ ] **Timing** — post Tue–Thu, ~14:00–15:00 UTC (HN's US-morning window).
- [ ] **Order** — Show HN first; the X thread ~30 min later linking the HN
      discussion; r/LocalLLaMA a few hours later (or next morning) so each
      audience gets a native post, not crossposting spam.
- [ ] **Be present** — answer every substantive comment for the first 3
      hours; technical humility beats marketing voice on HN.
- [ ] **Watch the pipes** — keep an eye on the Actions tab (any run failure)
      and Resend → Audience (signup wave arriving). The daily subscriber
      report card can be enabled with `LIST_REPORT_IN_EMAIL=true` for launch
      week.
