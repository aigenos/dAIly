# Private sections

This folder is an extension point. Modules you add here define **custom briefing
sections** that get merged into the daily digest automatically.

Everything in this folder is **gitignored** except `__init__.py`, `EXAMPLE.py`,
`opportunity.example.py`, and this README — so your custom section prompts stay
on your machine and never end up in the public repo or the published archive.

## The paid tier: "The Builder's Edge"

[`opportunity.example.py`](opportunity.example.py) is the ready-made **paid**
opportunity section — the deeper counterpart to the free "Opportunity of the Day"
in `analyzer.py`. It presents 3–5 buildable bets, each **prior-art-validated**
(the model web-searches for what already exists and justifies why the opening is
still open) and **memory-aware** (the prompt is fed your recent picks from
`docs/receipts.md`, so it won't re-pitch an idea). Activate it:

```bash
cp src/private/opportunity.example.py src/private/opportunity.py
# analyzer.py loads `opportunity` automatically; it's now gitignored.
```

To run it in CI without committing it, base64 the module into the
`OPPORTUNITY_B64` secret — the workflow restores it for the run only, so your
email + newsletter include it while the public archive has it stripped.

## Add a section

1. Copy `EXAMPLE.py` to a new file, e.g. `my_section.py`.
2. Edit `SECTION_ID`, `ORDER`, and `INSTRUCTIONS`.
3. Register it in [`../analyzer.py`](../analyzer.py) inside
   `_load_private_sections()`:
   ```python
   from .private import my_section
   out.append((my_section.SECTION_ID, my_section.ORDER, my_section.INSTRUCTIONS))
   ```

That's it. The section now appears in the digest at its `ORDER` position, and is
automatically **stripped from the public archive** (via its `<!--SECTION:id-->`
marker) so it stays private even when you publish the rest.

## Why it works this way

The digest's instruction prompt is composed from a list of section blocks. Public
sections live in `analyzer.py`; private ones load from here at runtime. A public
clone has no private modules, so it simply produces the briefing without them —
the prompt logic for your private sections is never in the public tree.
