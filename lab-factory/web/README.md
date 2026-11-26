# Lab Factory web

The web interface for Lab Factory. It is one statically exported Next.js page
where a researcher describes an experiment, talks to the factory, reads the
procedure and run plan it produces, and where an approver signs off a
submission by name. Analysis and simulation code run in the browser on a
self-hosted Python runtime, so readings never leave the machine. The app works
on built-in sample data with no backend at all.

## Quick start

Use Node 22 and run every command from `lab-factory/web/`.

```sh
npm ci
npm run dev
```

Open the address `next dev` prints. To build the static site and serve it:

```sh
npm run build
python3 -m http.server 4190 --bind 127.0.0.1 --directory out
```

The export is written to `out/` and works from any static file server, served
at the root of an origin (it loads its scripts and the Python runtime from
`/_next/` and `/runtime/`, so it can't live under a sub-path). Open
`http://127.0.0.1:4190/`. The host should send
`Content-Security-Policy: connect-src 'self'; font-src 'self'` (plus the
backend's origin in `connect-src` in live mode); see "Analysis code never reaches the network" in [API.md](API.md).

## Sample mode and live mode

By default the app runs in sample mode. It shows a fixed lab, two projects and
their experiments, and a banner says `Sample data. Nothing here is saved or
real.` No lab data is stored beyond the open page; only your theme choice is
kept.

Live mode talks to a backend. Only `NEXT_PUBLIC_LABFACTORY_API_URL` switches
the app to live mode; `NEXT_PUBLIC_LABFACTORY_LAB_ID` is optional. Both are
read at build time.

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_LABFACTORY_API_URL` | Base URL of the backend. When set, the app uses the live client. When unset, it uses sample data. |
| `NEXT_PUBLIC_LABFACTORY_LAB_ID` | Optional. The lab to show in live mode. Defaults to the sample lab id, `emory-biophys`. |

Live mode needs a backend that implements [API.md](API.md). That backend does
not exist yet, so live mode is the contract and a client, not something you
can run end to end today.

## The offline Python runtime

The analysis app and the simulation run Python in a web worker using Pyodide,
served from this origin. `scripts/copy-runtime.mjs` copies the Pyodide files
from `node_modules/pyodide` into `public/runtime/`. It runs before `dev` and
before `build`. Only `public/runtime/python-worker.mjs` is committed; the
copies are git-ignored.

The Python is standard library only. Readings are parsed and analyzed in the
browser and are never sent anywhere: once Pyodide has loaded, the worker
removes network access from the analysis code. Pyodide loads only from `/runtime/`, and
nothing is fetched from a CDN or from Google Fonts.

## Scripts

| Script | What it does |
|---|---|
| `npm run dev` | Copies the runtime, then starts the Next.js dev server. |
| `npm run build` | Copies the runtime, then writes the static export to `out/`. |
| `npm run typecheck` | Runs `tsc --noEmit` over the whole package. |
| `npm run test:unit` | Runs `node --test` over `lib/**/*.test.ts`. |
| `npm run test:py` | Runs the Python unit tests in `python/` with `python3 -I`. |
| `npm run test:e2e` | Runs the Playwright browser tests, including the axe accessibility pass in both themes, against `out/`. Build first. |

CI runs them in this order: typecheck, unit, Python, build, browser tests.

## Running the browser tests in a sandbox

The browser tests need Chromium. On a normal machine, install it with
`npx playwright install chromium`. In a sandbox that already has a Chromium,
point the tests at it instead and turn tracing off:

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium npm run test:e2e -- --trace off
```

The tests serve `out/` on port 4190. Set `PLAYWRIGHT_PORT` to use another port,
for example when two checkouts run tests at once.

## Map of the code

| Path | What is there |
|---|---|
| `app/` | The Next.js entry: layout, the single page, global styles and the icon. |
| `components/` | The screens and their parts, with CSS next to them. |
| `components/tabs/` | The five workspace tabs: Procedure, Run plan, Analysis app, Results and Simulation. |
| `lib/` | Plain TypeScript with no React: routes, types, formatting, checks display, history and diff logic, readings and analysis helpers, plotting. Unit tests sit next to the code. |
| `lib/sample/` | The sample client and its seed data, conversation script and records. |
| `lib/live/` | The live client for the backend in `API.md`. |
| `lib/runtime/` | The runner that talks to the Python worker. |
| `python/` | The analysis and simulation code run in the browser, and its tests. |
| `e2e/` | Playwright tests and shared helpers. |
| `public/` | Static files: skills, and `runtime/` with the committed worker. |

## Rules for contributors

- The UI never decides pass or fail. Checks come from the backend or the
  sample data, and the interface only shows them.
- Code in `lib/` runs under Node type stripping. Use no `enum`, `namespace`
  or constructor parameter properties, and end relative imports in `.ts`.
- Nothing comes from a CDN. Fonts come from Fontsource and Python from
  `/runtime/`.
- No skipped tests: no `test.skip`, `test.fixme` or `.only`. Accessibility
  checks get no rule exclusions; fix the cause.
- Colors come from the theme tokens in `app/globals.css`, in both themes.

## Where to read more

- [API.md](API.md): the backend contract for live mode.
- [The design spec](../docs/specs/2026-11-26-lab-factory-web-ui-design.md).
- [The implementation plan](../docs/plans/2026-11-26-web-ui.md).
- [The Lab Factory README](../README.md): the core, CLI and agent tools.
