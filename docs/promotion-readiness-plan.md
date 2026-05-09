# Promotion readiness plan

Goal: make `hermes-curator-evolver` easier to understand, evaluate, and discuss before sharing on Reddit or other builder communities.

## Patch plan

1. `README.md`
   - Add an early "who this is for" paragraph.
   - Add a compact trust boundary section before install commands.
   - Add links to demo/example artifacts.
   - Add a "Feedback wanted" section with concrete discussion prompts.

2. `docs/demo-script.md`
   - Provide a short terminal demo script that can later be recorded as GIF/asciinema.
   - Keep commands safe by default and mark write paths explicitly.

3. `examples/`
   - Add synthetic report/proposal/diff/rollback artifacts so readers can inspect expected behavior without installing first.

4. `docs/reddit-launch.md`
   - Add subreddit-specific launch notes and draft posts for `r/hermesagent`, `r/ArtificialInteligence`, and `r/MachineLearning`.
   - Include anti-spam guidance and a staggered posting cadence.

## Acceptance checks

- README top section answers "what is this, who is it for, why should I trust it?" within the first screen.
- Example artifacts are clearly synthetic and safe to inspect.
- Docs avoid asking for stars/upvotes and disclose author affiliation in post drafts.
- Existing tests still pass.
- Independent Claude Code review is requested before pushing.
