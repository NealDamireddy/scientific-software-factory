import { randomUUID } from "node:crypto";
import { expect, test } from "playwright/test";

test("a saved worker procedure opens inside its project and survives a reload", async ({ page, request, baseURL }) => {
  async function save(path, data) {
    const response = await request.post(path, {data, headers: {Origin: baseURL}});
    expect(response.ok()).toBeTruthy();
    return response.json();
  }

  const first = await save("/api/procedures", {demo: true});
  const draft = await save(`/api/procedures/${first.id}/source`, {});
  const detail = await (await request.get(`/api/orders/${draft.id}`)).json();
  expect(detail.order.status).toBe("in_review");
  expect(detail.draft.automatic).toBe(false);
  const project = detail.order.experiment_id;
  const investigation = await save("/api/investigations", {
    project_id: project,
    request_id: randomUUID(),
    objective: detail.order.objective,
    choices: {kind: "procedure"},
  });
  expect(investigation.resources).toEqual([expect.objectContaining({id: draft.id, reused: true})]);
  const url = "/#project/" + encodeURIComponent("lab:" + project) + "/" + investigation.id;
  await page.goto(url);
  const region = page.locator(".project-investigations");
  const text = "Read the absorbance of the reference solution.";
  await expect(region.getByRole("button", {name: "Procedure", exact: true})).toHaveAttribute("aria-expanded", "true");
  await expect(region.getByRole("listitem").filter({hasText: text})).toBeVisible();
  await page.setViewportSize({width: 390, height: 844});
  await page.reload();
  await expect(region.getByRole("button", {name: "Procedure", exact: true})).toHaveAttribute("aria-expanded", "true");
  await expect(region.getByRole("listitem").filter({hasText: text})).toBeVisible();
  await expect(region.getByRole("link", {name: /review/i}).first()).toHaveAttribute("href", "#order/" + draft.id);
  const viewport = await page.evaluate(() => {
    const el = document.scrollingElement;
    return {scroll: el.scrollWidth, client: el.clientWidth};
  });
  expect(viewport.scroll).toBeLessThanOrEqual(viewport.client + 1);
});
