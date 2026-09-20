import { expect, test } from "@playwright/test";
import type { SceneObject, Vector3 } from "../src/types";

const API = process.env.TEST_API_URL || "http://127.0.0.1:18114/api";
function box(
  id: string,
  kind: string,
  position: Vector3,
  size: Vector3,
): SceneObject {
  const vertices: Vector3[] = [];
  for (const x of [-0.5, 0.5])
    for (const y of [-0.5, 0.5])
      for (const z of [-0.5, 0.5]) {
        vertices.push([x * size[0], y * size[1], z * size[2]]);
      }
  return {
    id,
    kind,
    label: id,
    position,
    size,
    rotation: [0, 0, 0],
    scale: [1, 1, 1],
    confidence: 0.9,
    structural: kind === "floor",
    movable: kind !== "floor",
    editable: true,
    entrance: kind === "door",
    transient: false,
    provenance: "user_created",
    method: "test fixture",
    source_frames: [],
    supporting_surface: null,
    relationships: [],
    modified: false,
    deleted: false,
    original_transform: { position, rotation: [0, 0, 0], scale: [1, 1, 1] },
    geometry: {
      vertices,
      colors: vertices.map(() => [0.4, 0.6, 0.7]),
      triangles: [
        [0, 1, 3],
        [0, 3, 2],
        [4, 6, 7],
        [4, 7, 5],
        [0, 4, 5],
        [0, 5, 1],
        [2, 3, 7],
        [2, 7, 6],
        [0, 2, 6],
        [0, 6, 4],
        [1, 5, 7],
        [1, 7, 3],
      ],
    },
  };
}

test("route between doorways, clear after edits, and pick floor points", async ({
  page,
  request,
}) => {
  const scene = {
    version: 2,
    units: "estimated_meters",
    camera_path: [],
    camera_frames: [],
    objects: [
      box("floor", "floor", [0, -0.05, 0], [6, 0.1, 6]),
      box("West door", "door", [-2.9, 1, 0], [0.1, 2, 1.2]),
      box("East door", "door", [2.9, 1, 0], [0.1, 2, 1.2]),
      box("table", "table", [0, 0.5, 0], [1, 1, 1.5]),
    ],
  };
  const imported = await request.post(`${API}/scans/import`, {
    data: {
      format: "spatial-scene-v2",
      original: scene,
      scan: {
        id: "00000000-0000-0000-0000-000000000001",
        name: "Routing browser fixture",
        status: "degraded",
        processing_mode: "blender",
        scene,
      },
    },
  });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const scan = await imported.json();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/?scan=${scan.id}#modeler`);
  const canvas = page.getByTestId("scene-modeler").locator("canvas");
  await expect(canvas).toBeVisible();
  await page
    .getByLabel("Route start", { exact: true })
    .selectOption("West door");
  await page.getByLabel("Route end", { exact: true }).selectOption("East door");
  const response = page.waitForResponse((r) =>
    r.url().endsWith(`/scans/${scan.id}/routes`),
  );
  await page.getByRole("button", { name: "Find path", exact: true }).click();
  const routed = await response;
  expect(routed.ok(), await routed.text()).toBeTruthy();
  await expect(page.getByTestId("route-result")).toContainText(
    "Estimated path",
  );
  await expect(canvas).toHaveAttribute("data-route-markers", "2");
  expect(Number(await canvas.getAttribute("data-route-points"))).toBeGreaterThan(
    2,
  );
  await page.screenshot({ path: "test-results/pathfinder-route.png" });

  await page.getByLabel("Scene element").selectOption("table");
  await page.getByRole("button", { name: "Move right", exact: true }).click();
  await expect(page.getByTestId("route-result")).toHaveCount(0);
  await expect(canvas).toHaveAttribute("data-route-points", "0");
  await expect(
    page.getByRole("button", { name: "Find path", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Pick start in model" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Pick start in model" }).click();
  const rect = (await canvas.boundingBox())!;
  let picked = false;
  for (let y = 0.45; y <= 0.8 && !picked; y += 0.06) {
    for (let x = 0.25; x <= 0.75 && !picked; x += 0.08) {
      const px = rect.x + rect.width * x,
        py = rect.y + rect.height * y;
      await page.mouse.move(px, py);
      if ((await canvas.getAttribute("data-hovered")) === "floor") {
        await page.mouse.click(px, py);
        picked = true;
      }
    }
  }
  expect(picked).toBeTruthy();
  await expect(page.getByLabel("Route start", { exact: true })).toHaveValue(
    "point",
  );
  await expect(canvas).toHaveAttribute("data-route-markers", "1");
  await page.getByRole("button", { name: "Clear path", exact: true }).click();
  await expect(canvas).toHaveAttribute("data-route-markers", "0");
  expect(errors).toEqual([]);
});
