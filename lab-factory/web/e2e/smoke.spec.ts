import { expect, test } from "playwright/test";
import { goto } from "./helpers.ts";

test("the page loads with its title and main region", async ({ page }) => {
  await goto(page, "/");
  await expect(page).toHaveTitle("Lab Factory");
  await expect(page.getByRole("main")).toBeVisible();
});

test("the Python runtime is served from this origin", async ({ request }) => {
  const response = await request.get("/runtime/pyodide.mjs");
  expect(response.status()).toBe(200);
});

test.describe("with the system set to dark", () => {
  test.use({ colorScheme: "dark" });

  test("the page uses the dark ground colour", async ({ page }) => {
    await goto(page, "/");
    const background = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(background).toBe("rgb(20, 23, 31)");
  });
});
