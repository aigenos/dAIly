"""The Builder's Edge — the PAID / private opportunity section (template).

This is the premium counterpart to the free "🚀 Opportunity of the Day" teaser
in src/analyzer.py. The free teaser ships publicly (the viral hook); THIS section
is the paid tier — a deeper, prior-art-validated, memory-aware set of buildable
bets. It is stripped from the public archive via its <!--SECTION:--> marker and
PUBLIC_SENTINELS, so it reaches your email + your newsletter subscribers but
never the open archive.

ACTIVATE IT (it's gitignored by default so it stays your secret sauce):

    cp src/private/opportunity.example.py src/private/opportunity.py
    # edit to taste, then run as usual — analyzer.py loads `opportunity`
    # automatically. To run it in CI without committing it, base64 the module
    # into the OPPORTUNITY_B64 secret (see the workflow + src/private/README.md).

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

For EACH bet, an <h3> with a punchy product/project name, then a <ul> with these
EXACT bolded labels in order:
<ul>
<li><strong>The gap:</strong> the specific missing/broken piece in the stack,
cited to a real source above or one you verified via web search.</li>
<li><strong>Why now:</strong> the recent catalyst (new model, API, price drop,
benchmark, capability shift) that makes this newly tractable.</li>
<li><strong>Prior art &amp; why it's still open:</strong> SEARCH THE WEB for what
already exists — name the 1–3 nearest real products / repos / papers (with links)
and explain precisely why the opening remains (a gap they miss, a timing shift, a
better wedge, a different buyer). If the space is already well-served with no
defensible opening, DROP this bet and pick another. This validation is the whole
point of this section — never skip it.</li>
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
