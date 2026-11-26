# Lab Factory web

The web interface for Lab Factory. It is one statically exported Next.js page
that runs on sample data by default, and on a live backend when one is
configured. Analysis code runs in the browser on a self-hosted Python runtime
(Pyodide), so readings never leave the machine and nothing is fetched from a
CDN.

This package is self-contained. It imports nothing from the repo root `app/`,
from `factory/` or from `lab-factory/src/`.

## Run

Use Node 22 and run every command from `lab-factory/web/`.

```sh
npm ci
npm run dev
```

`npm run dev` and `npm run build` first run `scripts/copy-runtime.mjs`, which
copies the Pyodide files from `node_modules/pyodide` into `public/runtime/`.
Those copies are git-ignored.

## Build

```sh
npm run build
```

The static site is written to `out/`. Serve it with any static file server,
for example:

```sh
python3 -m http.server 4190 --bind 127.0.0.1 --directory out
```

## Test

```sh
npm run typecheck   # TypeScript, no emit
npm run test:unit   # node --test over lib/**/*.test.ts
npm run test:py     # python3 unittest over python/test_*.py
npm run build       # the browser tests run against out/
npm run test:e2e    # Playwright, serves out/ on port 4190
```

The browser tests need Chromium. Either install it with
`npx playwright install chromium`, or point the tests at an existing binary
with `PLAYWRIGHT_CHROMIUM_EXECUTABLE`:

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium npm run test:e2e -- --trace off
```

## Sample and live mode

Both variables are read at build time.

| Variable | Meaning |
|---|---|
| `NEXT_PUBLIC_LABFACTORY_API_URL` | Base URL of the Lab Factory backend. When set, the app uses the live client. When unset, it uses sample data. |
| `NEXT_PUBLIC_LABFACTORY_LAB_ID` | The lab to show in live mode. |

The live client is not built yet, so the app currently always runs on sample
data.
