import { expect, test } from "@playwright/test";

test("prepared demo opens directly with labeled doors and reuses its saved scan", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  const load = page.getByRole("button", { name: "Load prepared demo" });
  await expect(load).toBeEnabled();
  await load.click();
  await expect(page).toHaveURL(/scan=.+#modeler$/);
  const model = page.locator(
    '.modeler-view canvas[aria-label="Interactive 3D scan model"]',
  );
  await expect(model).toHaveAttribute("data-objects", "109", {
    timeout: 15000,
  });
  await expect(model).toHaveAttribute("data-highlighted-openings", "3");
  await expect(
    page.getByRole("heading", {
      name: "Prepared demo · Virginia lounge · IMG_1343",
    }),
  ).toBeVisible();
  const url = page.url();
  await page.getByRole("button", { name: "Return to dashboard" }).click();
  await load.click();
  await expect(page).toHaveURL(url);
  await expect(model).toHaveAttribute("data-objects", "109");
  expect(errors).toEqual([]);
});

test("matching reference upload shows ten-second prepared-model stages", async ({
  page,
}) => {
  const reference = process.env.DEMO_REFERENCE_VIDEO;
  test.skip(
    !reference,
    "Set DEMO_REFERENCE_VIDEO to the original local demo footage.",
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Load prepared demo" }).click();
  await expect(
    page.locator(".modeler-view canvas[data-objects]"),
  ).toHaveAttribute("data-objects", "109");
  await page.getByRole("button", { name: "Return to dashboard" }).click();
  const preview = page.locator(".environment-panel canvas");
  await expect(preview).toBeVisible();
  await page
    .getByRole("button", { name: "Video or Blender model" })
    .setInputFiles(reference!);
  await expect(preview).toHaveCount(0);
  await expect(page).not.toHaveURL(/scan=/);
  await expect(
    page.getByText("Click Reconstruct video to generate your 3D model."),
  ).toBeVisible();
  const sandbox = page.getByRole("button", {
    name: "Open the full 3D modeling environment",
  });
  await expect(sandbox).toBeDisabled();
  const responsePromise = page.waitForResponse(
    (r) => r.request().method() === "POST" && /\/api\/scans$/.test(r.url()),
  );
  await page
    .getByRole("button", { name: "Reconstruct video", exact: true })
    .click();
  const response = await responsePromise;
  expect(response.status()).toBe(202);
  const scan = await response.json();
  expect(scan.stage).toMatch(/^demo_/);
  const started = Date.now();
  const feedback = page.locator(".scan-feedback");
  await expect(feedback).toContainText("checking floors", { timeout: 6000 });
  await expect(page.locator(".job-progress progress")).toHaveAttribute(
    "value",
    "30",
  );
  await expect(feedback).toContainText("checking furnishings", {
    timeout: 5000,
  });
  await expect(preview).toHaveCount(0);
  await expect(sandbox).toBeDisabled();
  await expect(feedback).toContainText("loading Blender materials", {
    timeout: 5000,
  });
  await expect(preview).toHaveCount(0);
  await expect(sandbox).toBeDisabled();
  await expect(feedback).toContainText("preparing the Sandbox", {
    timeout: 5000,
  });
  await expect(preview).toHaveCount(0);
  await expect(sandbox).toBeDisabled();
  await expect(feedback).toContainText("Prepared demo ready", {
    timeout: 6000,
  });
  expect(Date.now() - started).toBeGreaterThanOrEqual(9500);
  await expect(preview).toBeVisible();
  await expect(sandbox).toBeEnabled();
  await expect(page.locator(".job-progress progress")).toHaveAttribute(
    "value",
    "100",
  );
  await page
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  await expect(
    page.locator(".modeler-view canvas[data-objects]"),
  ).toHaveAttribute("data-highlighted-openings", "3");
});
