"""The Builder's Edge — the PAID opportunity section.

This is the premium counterpart to the free "🚀 Opportunity of the Day" teaser
in src/analyzer.py. The free teaser ships publicly (the viral hook); THIS section
is the paid tier — a deeper, prior-art-validated, long-horizon set of buildable
bets. It is stripped from the public archive via its <!--SECTION:--> marker and
PUBLIC_SENTINELS, so it reaches your email + your newsletter subscribers but
never the open archive.

ACTIVATE IT (two ways):

  1. Bundled (simplest): set ENABLE_BUILDERS_EDGE=true. analyzer.py loads THIS
     module. The prompt is in the public repo, but the generated bets still go
     only to your email/subscribers (stripped from the public archive).

  2. Truly private (your secret sauce): copy this to src/private/opportunity.py
     (gitignored) and edit it — that file always wins over this bundled one. To
     run it in CI without committing it, base64 it into the OPPORTUNITY_B64
     secret (the workflow restores it for the run only).

Rename freely: change SECTION_ID, the <h2>, and PUBLIC_SENTINELS together.
"""

from __future__ import annotations

# Slug + marker. MUST match the <!--SECTION:builders_edge--> marker below so the
# archive/newsletter strippers can remove this section from public output.
SECTION_ID = "builders_edge"

# Slot it right after the free Opportunity teaser (opp_teaser=20), before Stack
# Signals (stack=30).
ORDER = 25

# Phrases that must NEVER appear in public output — a defense-in-depth leak
# check. If any of these survive stripping, publishing fails closed. Keep these
# in sync with the <h2> text if you rename the section.
PUBLIC_SENTINELS = ["The Builder's Edge", "Builder's Edge"]

INSTRUCTIONS = """\
<!--SECTION:builders_edge-->
<h2>🧭 The Builder's Edge — Validated Bets (5 min read)</h2>
This is the premium section. Go DEEPER than the free Opportunity of the Day above:
present 3–5 DISTINCT buildable bets, each rigorously validated. These must be
different from each other AND from the free pick above — no overlap.

RESEARCH HORIZON — judge over MONTHS, not days. For each bet, use web search to
trace its theme across the last 3–6 months: is it a durable, ACCELERATING trend
or a one-week blip? When did it first surface, and what has shipped since? Anchor
the bet in that arc (e.g. "first paper in March, two startups funded in April,
still no open-source tool"). A bet that can't show a multi-month trajectory is
probably too early or too noisy — say so or drop it.

For EACH bet, an <h3> with a punchy product/project name, then a <ul> with these
EXACT bolded labels in order:
<ul>
<li><strong>The gap:</strong> the specific missing/broken piece in the stack,
cited to a real source (from above or verified via web search).</li>
<li><strong>The 3–6 month arc:</strong> how this theme developed over recent
months (key papers/launches/funding, with links and rough dates) — proof it's a
durable trend, not a blip.</li>
<li><strong>Why now:</strong> the recent catalyst (new model, API, price drop,
benchmark, capability shift) that makes this newly tractable THIS week.</li>
<li><strong>Prior art &amp; why it's still open:</strong> SEARCH THE WEB over the
last 3–6 months for what already exists — name the 1–3 nearest real products /
repos / papers (with links) and explain precisely why the opening remains (a gap
they miss, a timing shift, a better wedge, a different buyer). If the space is
already well-served with no defensible opening, DROP this bet and pick another.</li>
<li><strong>Build as:</strong> arXiv paper / OSS library / dev tool / SaaS /
vertical app / startup — and why that shape fits.</li>
<li><strong>Wedge &amp; moat:</strong> first user, first dollar, and what
compounds (data, network, distribution) so a fast follower can't just copy it.</li>
<li><strong>Validation:</strong> AT LEAST TWO independent, linked demand signals
from unrelated sources, quantified where possible (upvotes, star velocity, round
size, waitlist). One Reddit/HN post alone is not enough.</li>
<li><strong>First two weeks:</strong> a concrete, sequenced plan to prototype and
get the first external signal.</li>
</ul>
Honor the ALREADY PROPOSED list in the prompt: do not re-pitch a prior idea unless
you state what is materially new. Rank the bets strongest-first. Be specific and
technical — this is the section subscribers pay for."""
