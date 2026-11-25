import { expect, test } from "playwright/test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Timeline } from "../../app/workspace/Timeline";
import { recordedRuns } from "../../app/workspace/fixture-runs";

const spec = { sha256: "spec", calibration: { id: "calibration" } };
const [complete, reused, pending, interrupted] = recordedRuns(spec, spec);
const render = (run) => renderToStaticMarkup(createElement(Timeline, { run }));

test("completed timing comes from stage events, independent of the projected wait", () => {
  const result = render({...complete, software_wait_s: 99});
  expect(result).toContain("Data waited <b>6 s</b> for software");
  expect(result).toContain("overlapped for <b>11 s</b>");
  expect(result).toContain("25–27 s");
  expect(render(reused)).not.toContain("Data waited");
});

test("missing and interrupted stage events never imply readiness or an elapsed wait", () => {
  expect(render(pending)).not.toContain('class="software"');
  expect(render(pending)).toContain('class="point"');
  expect(render(interrupted)).not.toContain("Data waited");
  const missing = render({...complete, software_finished_at:null, acquisition_started_at:null});
  expect(missing).not.toContain("overlapped");
  expect(missing).not.toContain("Data waited");
  expect(missing).not.toContain('class="acquisition"');
});
