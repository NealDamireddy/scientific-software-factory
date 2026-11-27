# Notes for Claude sessions in this repository

## How to talk with the owner

The owner is a scientist who is learning software terminology and wants to understand the project more deeply over time.

- Use plain, everyday language. Lead with what something means for the lab or for the project, then give the technical detail if it helps.
- The first time a technical term appears in a reply, explain it in a few words, using the definitions in `lab-factory/docs/plain-language-guide.md` (section 4). Use the same word for the same thing every time.
- If a needed term is not in that glossary, explain it and offer to add it.
- Prefer a short concrete example over an abstract description.
- Do not talk down, and do not hide real detail: give file names, numbers and commands, with one line saying what each is for.
- When there is a choice to make, say what the options mean in practice and recommend one.

## What this repository is

- `lab-factory/` is the current product. Read `lab-factory/docs/plain-language-guide.md` first: it holds the map of the parts, the glossary, the current state and the roadmap.
- `lab-factory/src/labfactory/` is the Python backend (the "engine").
- `lab-factory/public/` is the deployed reviewer site (plain JavaScript, talks to the real backend).
- `lab-factory/web/` is the newer researcher site (Next.js, sample data only; its `API.md` describes endpoints the backend does not serve yet).
- The top-level `factory/` and `app/` are the older EVOLVE demo, shown under `/evolve` in the reviewer site.

## Designs and plans

- Designs: `lab-factory/docs/specs/`. The founding one is `2026-11-25-lab-factory-architecture-design.md`; its "Anti-goals" section is the project's core promise.
- Plans: `lab-factory/docs/plans/`, one file per phase, as checklists. Tick boxes as steps are completed.
- Roadmap and open owner decisions: section 6 of the plain-language guide. Keep its status column current when a phase starts or finishes.

## Commands

Run backend commands from `lab-factory/`:

- Install: `uv sync --locked`
- Backend tests: `uv run --frozen pytest -q tests` (340 pass at commit `10bad3f`)

Run researcher-site commands from `lab-factory/web/`:

- `npm ci`, then `npm run typecheck`, `npm run test:unit`, `npm run test:py`, `npm run build`, `npm run test:e2e -- --trace off`

Run the combined reviewer site from the repository root:

- `npm ci`, `npm run build:lab`, then `npm start` (local) or `npm run test:lab` (one browser test)

## Working rules

- Write the test first, watch it fail, then make it pass.
- Never weaken, skip or delete a test to get a pass.
- The backend must not import from the top-level `factory/` package.
- Agents must never gain a way to approve or release work.
