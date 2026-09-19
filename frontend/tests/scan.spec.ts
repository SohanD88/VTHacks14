import { expect, test, type APIRequestContext } from "@playwright/test";
import type { ExportBundle, Scene, SceneObject } from "../src/types";
const API = process.env.TEST_API_URL || "http://127.0.0.1:8014/api";
function element(id: string, structural = false): SceneObject {
  return {
    id,
    label: structural ? "Opening candidate" : "Test chair",
    kind: structural ? "door" : "chair",
    confidence: 0.85,
    position: structural ? [2, 1, 0] : [0, 0.5, 0],
    rotation: [0, 0, 0],
    scale: [1, 1, 1],
    size: [1, 1, 1],
    geometry: {
      vertices: [
        [-0.5, -0.5, 0],
        [0.5, -0.5, 0],
        [0.5, 0.5, 0],
        [-0.5, 0.5, 0],
      ],
      colors: [
        [0.4, 0.7, 0.8],
        [0.4, 0.7, 0.8],
        [0.4, 0.7, 0.8],
        [0.4, 0.7, 0.8],
      ],
      triangles: [
        [0, 1, 2],
        [0, 2, 3],
      ],
    },
    structural,
    movable: !structural,
    editable: true,
    entrance: structural,
    transient: false,
    provenance: "depth_inferred",
    method: "test fixture",
    source_frames: [],
    supporting_surface: null,
    relationships: [],
    original_transform: {
      position: structural ? [2, 1, 0] : [0, 0.5, 0],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
    modified: false,
    deleted: false,
  };
}
async function fixture(
  request: APIRequestContext,
  moving = false,
  objects?: SceneObject[],
) {
  const original: Scene = {
    version: 2,
    units: "estimated_meters",
    objects: objects || [
      { ...element("chair"), transient: moving },
      element("door", true),
    ],
    camera_path: [
      [0, 1, 2],
      [1, 1, 2],
    ],
    camera_frames: [0, 1],
    unobserved: "Unknown",
    scale_note: "Approximate",
  };
  const bundle = {
    format: "spatial-scene-v2",
    original,
    scan: {
      id: "00000000-0000-0000-0000-000000000001",
      name: `Editor test ${Date.now()}`,
      source: "video",
      status: "degraded",
      processing_mode: "quick",
      scene: original,
      stats: { objects: 2, entrances: 1 },
      detections: [
        { kind: "chair", count: 1, confidence: 0.85 },
        { kind: "door", count: 1, confidence: 0.85 },
      ],
    },
  };
  const response = await request.post(API + "/scans/import", { data: bundle });
  expect(response.ok()).toBeTruthy();
  return await response.json();
}
test("selection, transforms, deletion, history, protection, export/import and dashboard sync", async ({
  page,
  request,
}) => {
  const scan = await fixture(request);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("Recent scans").selectOption(scan.id);
  await expect(page.getByTestId("object-count")).toHaveText("2");
  await page
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  const canvas = page.getByTestId("scene-modeler").locator("canvas");
  await expect(canvas).toBeVisible();
  const rect = (await canvas.boundingBox())!;
  let hit = false;
  for (let y = 0.25; y <= 0.75 && !hit; y += 0.1) {
    for (let x = 0.2; x <= 0.8 && !hit; x += 0.1) {
      await page.mouse.move(rect.x + rect.width * x, rect.y + rect.height * y);
      if (await canvas.getAttribute("data-hovered")) {
        hit = true;
        await page.mouse.click(
          rect.x + rect.width * x,
          rect.y + rect.height * y,
        );
      }
    }
  }
  expect(hit).toBe(true);
  await expect(page.getByLabel("Selected object details")).toBeVisible();
  await page.getByLabel("Scene element").selectOption("chair");
  await expect(page.getByLabel("Selected object details")).toContainText(
    "Test chair",
  );
  await page.getByRole("button", { name: "Move right", exact: true }).click();
  await expect(page.getByLabel("position X")).toHaveValue("0.10");
  await page.getByRole("button", { name: "Rotate 15°", exact: true }).click();
  await expect(page.getByLabel("rotation Y")).toHaveValue("15.00");
  await page
    .getByRole("button", { name: "Delete object", exact: true })
    .click();
  await expect(page.getByLabel("Scene element").locator("option")).toHaveCount(
    2,
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByLabel("Scene element").locator("option")).toHaveCount(
    3,
  );
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(page.getByLabel("Scene element").locator("option")).toHaveCount(
    2,
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByLabel("Scene element").locator("option")).toHaveCount(
    3,
  );
  await page.getByLabel("Scene element").selectOption("door");
  await expect(
    page.getByRole("button", { name: "Delete object", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Entrances / exits").uncheck();
  await page.getByLabel("Entrances / exits").check();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export JSON", exact: true }).click();
  const file = await download;
  const stream = await file.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  const bundle = JSON.parse(Buffer.concat(chunks).toString()) as ExportBundle;
  expect(bundle.scan.scene!.objects[0].position[0]).toBe(0.1);
  await page.getByLabel("Import scene file").setInputFiles({
    name: "scene.json",
    mimeType: "application/json",
    buffer: Buffer.concat(chunks),
  });
  await expect(page.getByRole("status")).toContainText("Export reloaded");
  await page.getByRole("button", { name: "Reset scene", exact: true }).click();
  await page.getByLabel("Scene element").selectOption("chair");
  await expect(page.getByLabel("position X")).toHaveValue("0.00");
  await page.getByRole("button", { name: "Return to dashboard" }).click();
  await expect(page.getByTestId("object-count")).toHaveText("2");
  expect(errors).toEqual([]);
});

test("video selection, upload failure and retry, measured progress, cancellation", async ({
  page,
}) => {
  await page.route("**/api/scans", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ json: [] })
      : route.continue(),
  );
  await page.goto("/");
  await page.getByLabel("Video file", { exact: true }).setInputFiles({
    name: "test.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("contract test"),
  });
  await expect(page.locator(".uploaded-video")).toBeVisible();
  let attempts = 0;
  await page.route("**/api/scans", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    attempts++;
    if (attempts === 1) return route.abort("failed");
    return route.fulfill({
      json: {
        id: "job-test",
        name: "Progress",
        status: "processing",
        progress: 37,
        stage: "decoding",
        processing_mode: "quick",
        message: "Read 74 frames",
        warnings: [],
        stats: {
          frames: 74,
          accepted: 4,
          rejected: 70,
          keyframes: 4,
          poses: 2,
          objects: 0,
          entrances: 0,
          artifact_bytes: 0,
          execution_device: "cpu",
        },
        detections: [],
        scene: null,
      },
    });
  });
  await page.route("**/api/scans/job-test/status", (route) =>
    route.fulfill({
      json: {
        id: "job-test",
        status: "processing",
        progress: 37,
        stage: "decoding",
        message: "Read 74 frames",
        stats: { frames: 74 },
        detections: [],
        warnings: [],
      },
    }),
  );
  await page
    .getByRole("button", { name: "Reconstruct video", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Cannot reach");
  await page
    .getByRole("button", { name: "Retry reconstruction", exact: true })
    .click();
  await expect(page.locator("progress")).toHaveAttribute("value", "37");
  await page.route("**/api/scans/job-test/cancel", (route) =>
    route.fulfill({ json: { status: "cancelling" } }),
  );
  await page.getByRole("button", { name: "Cancel processing" }).click();
  expect(attempts).toBe(2);
});

test("mobile navigation, empty state and invalid import", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#modeler");
  await expect(page.getByRole("status")).toBeEmpty();
  await expect(
    page.getByRole("button", { name: "Export JSON", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Import scene file").setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from("{}"),
  });
  await expect(page.getByRole("alert")).toContainText("Invalid scene");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/mobile-modeler.png",
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Return to dashboard" }).click();
  await expect(page.getByLabel("Video file", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "test-results/mobile-dashboard.png",
    fullPage: true,
    animations: "disabled",
  });
});

test("WebGL failure retains accessible object editing", async ({
  page,
  request,
}) => {
  const scan = await fixture(request);
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      type: string,
      ...args: unknown[]
    ) {
      if (type.includes("webgl")) return null;
      return original.apply(this, [type, ...args] as never);
    } as typeof HTMLCanvasElement.prototype.getContext;
  });
  await page.goto("/");
  await page.getByLabel("Recent scans").selectOption(scan.id);
  await expect(page.getByText("3D display unavailable").first()).toBeVisible();
  await page
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  await page.getByLabel("Scene element").selectOption("chair");
  await expect(page.getByLabel("Selected object details")).toContainText(
    "Test chair",
  );
});

test.afterEach(async ({ request }) => {
  const scans = await (await request.get(API + "/scans")).json();
  for (const scan of scans)
    if (scan.name.startsWith("Editor test ")) {
      await request.delete(API + "/scans/" + scan.id);
    }
});

test("moving candidates stay out of the permanent layer and preserve export metadata", async ({
  page,
  request,
}) => {
  const scan = await fixture(request, true);
  await page.goto("/");
  await page.getByLabel("Recent scans").selectOption(scan.id);
  await page
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  const canvas = page.getByTestId("scene-modeler").locator("canvas");
  await expect(canvas).toBeVisible();
  const rect = (await canvas.boundingBox())!;
  const findChair = async () => {
    for (let y = 0.3; y <= 0.7; y += 0.07) {
      for (let x = 0.2; x <= 0.8; x += 0.07) {
        await page.mouse.move(
          rect.x + rect.width * x,
          rect.y + rect.height * y,
        );
        if ((await canvas.getAttribute("data-hovered")) === "chair")
          return true;
      }
    }
    return false;
  };
  expect(await findChair()).toBe(false);
  await page.getByLabel("Moving candidates", { exact: true }).check();
  expect(await findChair()).toBe(true);
  await page.getByLabel("Scene element").selectOption("chair");
  await expect(page.getByLabel("Selected object details")).toContainText(
    "Moving candidate (separate layer)",
  );
  await page.screenshot({ path: "test-results/moving-candidate-layer.png" });
  const exported = await (
    await request.get(`${API}/scans/${scan.id}/export`)
  ).json();
  expect(
    exported.scan.scene.objects.find((o: SceneObject) => o.id === "chair")
      .transient,
  ).toBe(true);
  expect(
    exported.original.objects.find((o: SceneObject) => o.id === "chair")
      .transient,
  ).toBe(true);
  const restored = await request.post(API + "/scans/import", {
    data: exported,
  });
  expect(restored.ok()).toBeTruthy();
  const reloaded = await restored.json();
  expect(
    reloaded.scene.objects.find((o: SceneObject) => o.id === "chair").transient,
  ).toBe(true);
});

test("cutaway shows furniture through clipped walls and hides mounted insets", async ({
  page,
  request,
}) => {
  const wall: SceneObject = {
    ...element("wall", true),
    label: "Test wall",
    kind: "wall",
    entrance: false,
    position: [0, 1.5, 1],
    size: [3, 3, 0.025],
    geometry: {
      ...element("wall").geometry,
      // Reverse winding: the same observed wall must be visible from outside.
      triangles: [
        [0, 2, 1],
        [0, 3, 2],
      ],
      vertices: [
        [-1.5, -1.5, 0],
        [1.5, -1.5, 0],
        [1.5, 1.5, 0],
        [-1.5, 1.5, 0],
      ],
    },
    original_transform: {
      position: [0, 1.5, 1],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
  };
  const behind: SceneObject = {
    ...element("behind"),
    label: "Visible target behind wall",
    position: [-0.5, 2, 0],
    original_transform: {
      position: [-0.5, 2, 0],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
  };
  const mounted: SceneObject = {
    ...element("mounted"),
    label: "Mounted artwork",
    kind: "painting",
    position: [0.9, 2.2, 1.02],
    relationships: ["boundary:wall"],
    original_transform: {
      position: [0.9, 2.2, 1.02],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
  };
  const detached: SceneObject = {
    ...element("detached"),
    label: "Freestanding artwork",
    kind: "painting",
    position: [3, 2.2, 0],
    original_transform: {
      position: [3, 2.2, 0],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
    },
  };
  const scan = await fixture(request, false, [wall, behind, mounted, detached]);
  await page.goto("/");
  await page.getByLabel("Recent scans").selectOption(scan.id);
  await page
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  const canvas = page.getByTestId("scene-modeler").locator("canvas");
  await expect(canvas).toBeVisible();
  const rect = (await canvas.boundingBox())!;
  const find = async (wanted: string) => {
    for (let y = 0.15; y <= 0.85; y += 0.035) {
      for (let x = 0.15; x <= 0.85; x += 0.035) {
        const point = {
          x: rect.x + rect.width * x,
          y: rect.y + rect.height * y,
        };
        await page.mouse.move(point.x, point.y);
        if ((await canvas.getAttribute("data-hovered")) === wanted)
          return point;
      }
    }
    return undefined;
  };
  // With structure hidden, locate visible furniture by actual raycast feedback.
  await page.getByLabel("Structural geometry", { exact: true }).uncheck();
  const target = await find("behind");
  expect(target).toBeTruthy();
  await page.getByLabel("Structural geometry", { exact: true }).check();
  await page.mouse.move(target!.x, target!.y);
  await expect(canvas).toHaveAttribute("data-hovered", "behind");
  await page.mouse.click(target!.x, target!.y);
  await expect(page.getByLabel("Selected object details")).toContainText(
    "Visible target behind wall",
  );
  expect(await find("mounted")).toBeUndefined();
  expect(await find("detached")).toBeTruthy();
  await page.screenshot({ path: "test-results/cutaway-mounted-surfaces.png" });
  await page.getByLabel("Cutaway walls / ceiling", { exact: true }).uncheck();
  await page.mouse.move(target!.x, target!.y);
  await expect(canvas).toHaveAttribute("data-hovered", "wall");
  expect(await find("mounted")).toBeTruthy();
  await page.screenshot({
    path: "test-results/full-wall-mounted-surfaces.png",
  });
  // Rendering preferences never change the persisted scene or its exported geometry.
  const unchanged = await (await request.get(`${API}/scans/${scan.id}`)).json();
  expect(unchanged.scene).toEqual(scan.scene);
  await page.getByLabel("Scene element").selectOption("mounted");
  await page.getByRole("button", { name: "Move right", exact: true }).click();
  await expect(page.getByLabel("position X")).toHaveValue("1.00");
  await page.getByLabel("Cutaway walls / ceiling", { exact: true }).check();
  // A user-moved surface must not be hidden using its old boundary relationship.
  expect(await find("mounted")).toBeTruthy();
});

test("Sandbox doorway scale picks, history, persistence, export and mobile controls", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const door = element("door", true);
  door.observed_geometry = structuredClone(door.geometry);
  const scan = await fixture(request, false, [element("chair"), door]);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("Recent scans").selectOption(scan.id);
  await page
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  const canvas = page.getByTestId("scene-modeler").locator("canvas");
  await expect(canvas).toBeVisible();
  await expect(page.getByLabel("Reference width (feet)")).toHaveValue("3.5");
  await expect(
    page.getByRole("button", { name: "Apply room scale", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Pick doorway width", exact: true })
    .click();
  const box = (await canvas.boundingBox())!;
  let picks: { x: number; y: number }[] = [];
  for (let y = 0.3; y <= 0.8 && picks.length < 2; y += 0.05) {
    const row: { x: number; y: number }[] = [];
    for (let x = 0.2; x <= 0.9; x += 0.025) {
      const point = { x: box.x + box.width * x, y: box.y + box.height * y };
      await page.mouse.move(point.x, point.y);
      if ((await canvas.getAttribute("data-hovered")) === "door")
        row.push(point);
    }
    if (row.length >= 3) picks = [row[0], row[row.length - 1]];
  }
  expect(picks).toHaveLength(2);
  await page.mouse.click(picks[0].x, picks[0].y);
  await expect(canvas).toHaveAttribute("data-reference-points", "1");
  await page.mouse.click(picks[1].x, picks[1].y);
  await expect(canvas).toHaveAttribute("data-reference-points", "2");
  await expect(page.getByTestId("reference-progress")).toContainText(
    "Two reference points selected",
  );
  await page.getByLabel("Reference width (feet)").fill("0");
  await expect(
    page.getByRole("button", { name: "Apply room scale", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Reference width (feet)").fill("3.5");
  // A failed save keeps the chosen reference and the original scene intact for retry.
  await page.route("**/api/scans/*/calibration", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { message: "Scale save unavailable; retry." },
      }),
    }),
  );
  await page
    .getByRole("button", { name: "Apply room scale", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Scale save unavailable");
  expect(
    (await (await request.get(API + `/scans/${scan.id}`)).json()).scene
      .calibration,
  ).toBeNull();
  await expect(canvas).toHaveAttribute("data-reference-points", "2");
  await page.unroute("**/api/scans/*/calibration");
  await page
    .getByRole("button", { name: "Apply room scale", exact: true })
    .click();
  await expect(page.getByTestId("scale-status")).toContainText(
    "user-assumed 1.0668 m",
  );
  const saved = (await (await request.get(API + `/scans/${scan.id}`)).json())
    .scene as Scene;
  const reference = saved.calibration!;
  const factor =
    reference.distance_m /
    Math.hypot(
      ...reference.reference_points[0].map(
        (v, i) => v - reference.reference_points[1][i],
      ),
    );
  for (let i = 0; i < saved.objects.length; i++) {
    expect(saved.objects[i].geometry).toEqual(scan.scene.objects[i].geometry);
    expect(saved.objects[i].scale[0]).toBeCloseTo(factor, 8);
    expect(saved.objects[i].position[0]).toBeCloseTo(
      scan.scene.objects[i].position[0] * factor,
      8,
    );
    expect(saved.objects[i].modified).toBe(false);
  }
  expect(saved.camera_path[0][2]).toBeCloseTo(
    scan.scene.camera_path[0][2] * factor,
    8,
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByTestId("scale-status")).toContainText(
    "No reference width applied",
  );
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(page.getByTestId("scale-status")).toContainText(
    "user-assumed 1.0668 m",
  );
  await page.reload();
  await expect(page.getByTestId("scale-status")).toContainText(
    "user-assumed 1.0668 m",
  );
  await page.getByLabel("Scene element").selectOption("chair");
  await page.getByRole("button", { name: "Move right", exact: true }).click();
  await expect(page.getByLabel("position X")).toHaveValue("0.10");
  await page.getByLabel("Scene element").selectOption("door");
  await expect(
    page.getByRole("button", { name: "Delete object", exact: true }),
  ).toBeDisabled();
  await page.screenshot({ path: "test-results/calibration-sandbox.png" });
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export JSON", exact: true }).click();
  const stream = await (await download).createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  const bundle = JSON.parse(Buffer.concat(chunks).toString()) as ExportBundle;
  expect(bundle.scan.scene!.calibration).toEqual(reference);
  expect(bundle.original.calibration).toBeNull();
  expect(bundle.scan.scene!.objects[0].position[0]).toBe(0.1);
  await page.getByLabel("Import scene file").setInputFiles({
    name: "calibrated-scene.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(bundle)),
  });
  await expect(
    page.getByText("Export reloaded and saved as a new scan."),
  ).toBeVisible();
  await expect(page.getByTestId("scale-status")).toContainText(
    "user-assumed 1.0668 m",
  );
  const imported = await page.getByLabel("Recent scans").inputValue();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Reference width (feet)").scrollIntoViewIfNeeded();
  await expect(page.getByLabel("Reference width (feet)")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/calibration-mobile.png" });
  await page
    .getByRole("button", { name: "Remove scale reference", exact: true })
    .click();
  await expect(page.getByTestId("scale-status")).toContainText(
    "No reference width applied",
  );
  const unscaled = (
    await (await request.get(API + `/scans/${imported}`)).json()
  ).scene;
  expect(unscaled.objects[0].position[0]).toBeCloseTo(0.1 / factor, 8);
  await page.getByRole("button", { name: "Reset scene", exact: true }).click();
  await expect(
    page.getByText("Original reconstruction restored."),
  ).toBeVisible();
  expect(
    (await (await request.get(API + `/scans/${imported}`)).json()).scene,
  ).toEqual(bundle.original);
  expect(errors).toEqual([]);
  await request.delete(API + `/scans/${imported}`);
  await request.delete(API + `/scans/${scan.id}`);
});
