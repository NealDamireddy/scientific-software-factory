// Exercise the exact downloaded artifact using held-out inputs. Run from any directory.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const context = await browser.newContext({ offline: true, acceptDownloads: true, viewport: { width: 1180, height: 1250 } });
    const page = await context.newPage();
    const network = [];
    page.on("request", req => { if (/^https?:/.test(req.url())) network.push(req.url()); });
    await page.goto(pathToFileURL(path.join(__dirname, "app.html")).href);
    const frame = page.frameLocator("iframe");
    const input = frame.locator('input[type="file"]');
    const status = frame.locator("#status");
    const download = frame.getByRole("button", { name: "Download CSV" });
    const first = path.join(__dirname, "scan-A.csv");
    const second = path.join(__dirname, "scan-B.csv");
    const fileB = await fs.readFile(second, "utf8");

    async function readExport() {
      const event = page.waitForEvent("download");
      await download.click();
      const file = await event;
      const csv = await fs.readFile(await file.path(), "utf8");
      const [header, ...rows] = csv.trim().split(/\r?\n/);
      assert.equal(header, "corrected_energy_eV,normalized_intensity_det_ct_per_mon_ct");
      assert.ok(await frame.locator("#plot").isVisible());
      return rows.map(line => line.split(",").map(Number));
    }

    function checkBins(actual, expected) {
      assert.equal(actual.length, expected.length);
      for (const [i, [energy, intensity]] of actual.entries()) {
        assert.equal(energy, expected[i][0]);
        assert.ok(Math.abs(intensity - expected[i][1]) < 1e-12, `Intensity at ${energy}: ${intensity}`);
      }
    }

    await input.setInputFiles([first, second]);
    const expected = [[-1, 55 / 40], [0, 50 / 15], [1, 30 / 20]];
    checkBins(await readExport(), expected);
    assert.match(await frame.locator("table").innerText(), /scan-A\.csv/);
    assert.match(await frame.locator("table").innerText(), /scan-B\.csv/);
    if (process.argv[2]) await page.screenshot({ path: process.argv[2], fullPage: true });

    const scanA = { name: "scan-A.csv", mimeType: "text/csv", buffer: await fs.readFile(first) };
    const modified = text => ({ name: "changed.csv", mimeType: "text/csv", buffer: Buffer.from(text) });
    await input.setInputFiles([scanA, modified(fileB.replace("25,15", "40,15"))]);
    checkBins(await readExport(), [[-1, 55 / 40], [0, 50 / 15], [1, 45 / 20]]);

    for (const [from, to, reason] of [
      ["101.5,100.5", "101.7,100.5", /grid|match|tolerance/i],
      ["25,15", "25,0", /monitor|mon_ct/i],
      ["25,15", "-1,15", /detector|det_ct/i],
      ["101.5,100.5", "101.5,100.4", /marker/i],
      ["101.5,100.5", "99.5,100.5", /duplicate/i],
      ["25,15", "NaN,15", /numeric|finite|number/i],
    ]) {
      await input.setInputFiles([scanA, modified(fileB.replace(from, to))]);
      await frame.locator('#status[data-error="true"]').waitFor();
      assert.match(await status.innerText(), reason);
      assert.equal(await download.isVisible(), false);
    }
    assert.deepEqual(network, []);
    console.log("Passed original and changed exports, figure and file identities, six invalid inputs, offline operation.");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
