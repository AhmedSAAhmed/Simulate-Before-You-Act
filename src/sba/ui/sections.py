"""Static page sections as HTML. Dynamic values are escaped."""

from __future__ import annotations

from html import escape

REPO_URL = "https://github.com/AhmedSAAhmed/Simulate-Before-You-Act"

STAGES: tuple[tuple[str, str, str], ...] = (
    ("01", "Intent", "Your request becomes a typed plan. Targets are filters over live data, never ids the model typed."),
    ("02", "Simulate", "Read-only calls to the real systems. Code computes every effect; a second model hunts for side effects."),
    ("03", "Present", "One screen: the diff, money moved, who is affected and how to undo it. Blockers disable Approve."),
    ("04", "Execute", "Only the approved plan, only against the state it was simulated on. Canary first, every write journaled."),
    ("05", "Verify", "Observed vs predicted. Any surprise halts the run and rolls back what can be rolled back."),
)


def hero() -> str:
    return f"""
<section class="sba-hero">
  <div class="sba-wrap">
    <nav class="sba-nav">
      <a class="sba-brand" href="#top">SBA</a>
      <div class="sba-links">
        <a href="#pipeline">Pipeline</a><a href="#systems">Systems</a><a href="#try">Try it</a>
        <a href="{REPO_URL}" target="_blank" rel="noopener">Source</a>
      </div>
      <a class="sba-btn-dark" href="#try">Run a simulation</a>
    </nav>
    <div class="sba-hero-copy">
      <h1>See what your agent will <em>change</em> before it acts</h1>
    </div>
    <div class="sba-hero-foot">
      <p>Every credit, message and deletion is simulated against the real systems first, then runs only
      exactly as you approved it.</p>
      <a href="#pipeline">How it works&nbsp;&rsaquo;</a>
    </div>
  </div>
</section>"""


def pipeline() -> str:
    cells = "".join(
        f'<div class="sba-cell"><span class="sba-step">{n}</span><h3>{escape(title)}</h3><p>{escape(body)}</p></div>'
        for n, title, body in STAGES
    )
    return f"""
<section class="sba-section" id="pipeline">
  <div class="sba-wrap">
    <p class="sba-eyebrow">/// How it works</p>
    <h2 class="sba-h2">From a request to a <em>reviewed</em> write</h2>
    <p class="sba-lede">Five stages. Each ends at a check, and a failed check stops the run before anything
    reaches a real system.</p>
    <div class="sba-grid sba-grid-5">{cells}</div>
  </div>
</section>"""


def systems(status: dict[str, bool]) -> str:
    cells = "".join(
        f'<div class="sba-cell"><span class="sba-pill {"ok" if on else "off"}"><span class="sba-dot"></span>'
        f'{"connected" if on else "not configured"}</span><h3>{escape(name)}</h3></div>'
        for name, on in status.items()
    )
    return f"""
<section class="sba-section" id="systems">
  <div class="sba-wrap">
    <p class="sba-eyebrow">/// Real systems</p>
    <h2 class="sba-h2">No mocks <em>behind</em> the preview</h2>
    <p class="sba-lede">The simulation reads the same systems the agent writes to. Status reflects this
    server's configuration.</p>
    <div class="sba-grid sba-grid-4">{cells}</div>
  </div>
</section>"""


def try_intro() -> str:
    return """
<section class="sba-section" id="try">
  <div class="sba-wrap">
    <p class="sba-eyebrow">/// Try it</p>
    <h2 class="sba-h2">Ask for something <em>risky</em></h2>
    <p class="sba-lede">Describe the change in plain words. You will see the simulation before anything runs.</p>
  </div>
</section>"""


def footer() -> str:
    return f"""
<div class="sba-wrap">
  <footer class="sba-footer">
    <span>Simulate Before You Act · built for the DOO Builders League</span>
    <a href="{REPO_URL}" target="_blank" rel="noopener">Source on GitHub</a>
  </footer>
</div>"""
