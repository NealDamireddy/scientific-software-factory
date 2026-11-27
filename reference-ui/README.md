# Emory Biophysics reference UI

A standalone Next.js and TypeScript prototype for visual review. All scientific records, approvals, and instrument activity are illustrative. Local browser storage holds demo changes. Use a separate browser profile for a fresh workspace.

## Run locally

From this directory with Node.js 22 or newer:

```sh
npm ci
npm run dev
```

Open the localhost address printed by Next.js. The app includes its Geist font files through the Geist package.

## Review the B12 workflow

1. Enter “Vitamin B12 concentration” in the homepage composer and select the B12 project.
2. Open the draft and start the simulation. Inspect the flagged original sample alongside its calibration range.
3. Request changes and resubmit, or approve a simulated repeat. Compare the original and repeated runs and inspect their evidence.
4. Open the seeded absorbance time course to compare the two visualization types.

## Verify the build

```sh
npm run build
npm run typecheck
npm start
```
