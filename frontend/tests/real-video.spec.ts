import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { basename, extname } from "node:path";
import type { ScanResponse } from "../src/types";
test.skip(
  !process.env.RUN_REAL_VIDEO,
  "Run evaluate_videos.py first, then RUN_REAL_VIDEO=1",
);
const API = process.env.TEST_API_URL || "http://127.0.0.1:8014/api";
const mode = process.env.REAL_VIDEO_MODE || "balanced";
const resultsDirectory =
  process.env.REAL_VIDEO_RESULTS_DIR || "../test-results/real-video";
const inputs: { video: string; scan_id: string; result_file: string }[] =
  process.env.RUN_REAL_VIDEO
    ? JSON.parse(
        readFileSync(`${resultsDirectory}/manifest-${mode}.json`, "utf8"),
      )
    : [];
for (const input of inputs) {
  const stem = `${basename(input.video, extname(input.video))}-${mode}`;
  test(`${stem}: actual result, rendered geometry, hover, edit and export`, async ({
    page,
    request,
  }) => {
    test.setTimeout(120000);
    const result = JSON.parse(
      readFileSync(`${resultsDirectory}/${input.result_file}`, "utf8"),
    ) as ScanResponse;
    if (
      result.scene?.objects.some((o) =>
        o.method.startsWith("Robust vertical plane"),
      )
    ) {
      const registration = await request.get(
        `${API}/scans/${result.id}/artifacts/registration.json`,
      );
      const structure = await request.get(
        `${API}/scans/${result.id}/artifacts/structure-fit.json`,
      );
      expect(registration.ok()).toBeTruthy();
      expect(structure.ok()).toBeTruthy();
      const poseResponse = await request.get(
        `${API}/scans/${result.id}/artifacts/camera-poses.json`,
      );
      expect(poseResponse.ok()).toBeTruthy();
      const poses = await poseResponse.json();
      const localized = poses.filter(
        (pose: { success: boolean }) => pose.success,
      );
      expect(localized.length).toBe(result.stats.poses);
      expect(poses.length - localized.length).toBe(result.stats.pose_failures);
      for (const pose of localized.filter(
        (pose: { recovered?: boolean }) => pose.recovered,
      )) {
        expect(pose.method).toBe("multiview_relocalization");
        expect(pose.inliers).toBeGreaterThanOrEqual(20);
        expect(new Set(pose.reference_frames).size).toBeGreaterThanOrEqual(2);
        for (const reference of pose.reference_frames) {
          expect(
            localized.some(
              (other: { frame: number }) => other.frame === reference,
            ),
          ).toBe(true);
        }
        expect(
          result.scene.objects.some((object) =>
            object.source_frames.includes(pose.frame),
          ),
        ).toBe(true);
      }
      const alignment = await registration.json();
      expect(alignment.views).toBe(result.stats.poses);
      if (alignment.accepted) {
        expect(alignment.after.median_3d_m).toBeLessThan(
          alignment.before.median_3d_m,
        );
        expect(alignment.after.median_reprojection_px).toBeLessThanOrEqual(
          alignment.before.median_reprojection_px * 1.05,
        );
      }
      const consolidated = await request.get(
        `${API}/scans/${result.id}/artifacts/instance-tracks.json`,
      );
      expect(consolidated.ok()).toBeTruthy();
      for (const merge of await consolidated.json()) {
        expect(Math.min(...merge.reciprocal_overlap)).toBeGreaterThanOrEqual(
          0.55,
        );
        expect(new Set(merge.source_frames).size).toBe(
          merge.source_frames.length,
        );
      }
      const motion = await request.get(
        `${API}/scans/${result.id}/artifacts/motion-report.json`,
      );
      expect(motion.ok()).toBeTruthy();
      for (const track of await motion.json()) {
        for (const id of track.object_ids) {
          expect(result.scene.objects.some((o) => o.id === id)).toBe(true);
        }
        if (track.status === "moving_candidate") {
          expect(track.consecutive_motion_pairs).toBeGreaterThanOrEqual(2);
        }
      }
      const fixtureResponse = await request.get(
        `${API}/scans/${result.id}/artifacts/fixture-fit.json`,
      );
      if (
        result.scene.objects.some((o) =>
          o.method.includes("observed ceiling-plane fit"),
        )
      ) {
        expect(fixtureResponse.ok()).toBe(true);
      }
      if (fixtureResponse.ok()) {
        const fixtureReport = await fixtureResponse.json();
        for (const fit of fixtureReport.fixtures) {
          const object = result.scene.objects.find(
            (o) => o.id === fit.object_id,
          )!;
          const ceiling = fixtureReport.ceiling_planes.find(
            (plane: { object_id: string }) =>
              plane.object_id === fit.ceiling_id,
          );
          expect(object.kind).toBe("light");
          expect(object.structural).toBe(true);
          expect(object.movable).toBe(false);
          expect(object.supporting_surface).toBe(fit.ceiling_id);
          expect(object.observed_geometry?.vertices.length).toBeGreaterThan(0);
          expect(fit.supporting_frames.length).toBeGreaterThanOrEqual(3);
          for (const frame of fit.supporting_frames) {
            expect(object.source_frames).toContain(frame);
            expect(fit.mask_support[String(frame)]).toBeGreaterThanOrEqual(
              0.55,
            );
          }
          for (const point of object.geometry.vertices) {
            const distance = point.reduce(
              (sum, value, axis) =>
                sum +
                (value + object.position[axis] - ceiling.center[axis]) *
                  ceiling.normal[axis],
              0,
            );
            expect(Math.abs(distance)).toBeLessThan(0.00001);
          }
        }
      }
      const openingResponse = await request.get(
        `${API}/scans/${result.id}/artifacts/opening-fit.json`,
      );
      if (
        result.scene.objects.some((o) =>
          o.method.includes("RGB-D opening outline"),
        )
      ) {
        expect(openingResponse.ok()).toBe(true);
      }
      if (openingResponse.ok()) {
        const openingReport = await openingResponse.json();
        for (const fit of openingReport.openings) {
          const object = result.scene.objects.find(
            (o) => o.id === fit.object_id,
          )!;
          expect(object.entrance && object.structural && !object.movable).toBe(
            true,
          );
          expect(object.provenance).toBe("primitive_fitted");
          expect(object.observed_geometry?.vertices.length).toBeGreaterThan(0);
          expect(fit.supporting_frames.length).toBeGreaterThanOrEqual(3);
          expect(fit.plane_support).toBeGreaterThanOrEqual(0.75);
          expect(fit.lower_edge).toBe("inferred from observed floor");
          for (const frame of fit.supporting_frames) {
            expect(object.source_frames).toContain(frame);
            const evidence = fit.view_support[String(frame)];
            expect(evidence.floor_fraction).toBeGreaterThanOrEqual(0.15);
            for (const side of evidence.boundaries) {
              expect(side.depth_error_m).toBeLessThanOrEqual(0.2);
              expect(side.gap_fraction).toBeGreaterThanOrEqual(0.7);
            }
          }
          expect(
            Math.min(
              ...object.geometry.vertices.map((v) => v[1] + object.position[1]),
            ),
          ).toBeCloseTo(0, 6);
          for (const face of object.geometry.triangles) {
            const x =
              face.reduce((sum, i) => sum + object.geometry.vertices[i][0], 0) /
              3;
            const y =
              face.reduce((sum, i) => sum + object.geometry.vertices[i][1], 0) /
              3;
            expect(
              Math.abs(x) < fit.clear_width * 0.4 && y < fit.clear_height * 0.4,
            ).toBe(false);
          }
          if (fit.boundary_id) {
            expect(
              result.scene.objects.some((o) => o.id === fit.boundary_id),
            ).toBe(true);
            expect(object.relationships).toContain(
              `boundary:${fit.boundary_id}`,
            );
          }
        }
      }
      const planes = await structure.json();
      for (const support of planes.plane_orientation_support ?? []) {
        const wall = result.scene.objects.find(
          (o) => o.id === support.object_id,
        )!;
        expect(wall.kind).toBe("wall");
        expect(wall.observed_geometry?.vertices.length).toBe(support.vertices);
        expect(support.locally_oriented_vertices).toBe(support.vertices);
        expect(support.median_normal_agreement).toBeGreaterThan(0.9);
        expect(wall.method).toContain("local surface orientation");
      }
      for (const corner of planes.corner_junctions ?? []) {
        expect(corner.maximum_displacement).toBeLessThanOrEqual(0.31);
        expect(corner.supported_height_bins.length).toBeGreaterThanOrEqual(4);
        const seamHeights: Set<number>[] = [];
        for (const id of corner.walls) {
          const wall = result.scene.objects.find((o) => o.id === id);
          expect(wall?.structural).toBe(true);
          const seam = wall!.geometry.vertices.filter(
            (v) =>
              Math.hypot(
                v[0] + wall!.position[0] - corner.intersection_xz[0],
                v[2] + wall!.position[2] - corner.intersection_xz[1],
              ) < 0.0002,
          );
          seamHeights.push(
            new Set(
              seam.map((v) =>
                Math.round((v[1] + wall!.position[1]) / corner.grid_spacing),
              ),
            ),
          );
          expect(wall?.observed_geometry).toBeTruthy();
          expect(wall?.relationships).toContain(
            `adjacent:${corner.walls.find((other: string) => other !== id)}`,
          );
        }
        expect(
          [...seamHeights[0]].filter((y) => seamHeights[1].has(y)).length,
        ).toBeGreaterThanOrEqual(4);
      }
      expect(planes.wall_planes).toBe(
        result.scene.objects.filter((o) => o.kind === "wall").length,
      );
    }
    await page.goto("/");
    await page.getByLabel("Recent scans").selectOption(result.id);
    await expect(page.getByTestId("object-count")).toHaveText(
      String(result.stats.objects),
    );
    await expect(
      page.getByTestId("scene-preview").locator("canvas"),
    ).toBeVisible();
    await expect(page.locator(".live-badge").first()).toHaveText("Saved video");
    await expect
      .poll(async () =>
        Number(
          await page
            .getByTestId("scene-preview")
            .locator("canvas")
            .getAttribute("data-fps"),
        ),
      )
      .toBeGreaterThan(0);
    await page.screenshot({
      path: `test-results/${stem}-dashboard.png`,
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Open the full 3D modeling environment" })
      .click();
    const canvas = page.getByTestId("scene-modeler").locator("canvas");
    await expect(canvas).toBeVisible();
    await expect
      .poll(async () => Number(await canvas.getAttribute("data-fps")))
      .toBeGreaterThan(0);
    await page.getByLabel("Observed surfaces", { exact: true }).check();
    await expect
      .poll(async () => Number(await canvas.getAttribute("data-fps")))
      .toBeGreaterThan(0);
    await page.getByLabel("Observed surfaces", { exact: true }).uncheck();
    await expect
      .poll(async () => Number(await canvas.getAttribute("data-fps")))
      .toBeGreaterThan(0);
    const bounds = (await canvas.boundingBox())!;
    let hovered = false;
    for (let y = 0.3; y < 0.9 && !hovered; y += 0.08) {
      for (let x = 0.2; x < 0.85 && !hovered; x += 0.08) {
        await page.mouse.move(
          bounds.x + bounds.width * x,
          bounds.y + bounds.height * y,
        );
        hovered = !!(await canvas.getAttribute("data-hovered"));
        if (hovered)
          await page.mouse.click(
            bounds.x + bounds.width * x,
            bounds.y + bounds.height * y,
          );
      }
    }
    expect(hovered).toBe(true);
    await expect(page.getByLabel("Selected object details")).toBeVisible();
    const recoveredLight = result.scene!.objects.find(
      (o) => o.kind === "light" && o.method.includes("adaptive pixel sampling"),
    );
    if (recoveredLight) {
      await page.getByLabel("Scene element").selectOption(recoveredLight.id);
      await expect(page.getByLabel("Selected object details")).toContainText(
        recoveredLight.label,
      );
      expect(recoveredLight.source_frames.length).toBeGreaterThanOrEqual(3);
      expect(recoveredLight.geometry.triangles.length).toBeGreaterThan(0);
      if (recoveredLight.structural) {
        await expect(
          page.getByRole("button", { name: "Move right", exact: true }),
        ).toBeDisabled();
        await expect(
          page.getByRole("button", { name: "Delete object", exact: true }),
        ).toBeDisabled();
      }

      const evidence = page.getByText(
        `Source-frame evidence (${recoveredLight.source_frames.length})`,
        { exact: true },
      );
      await evidence.click();
      const sourceImage = page.getByAltText(
        `Source frame ${recoveredLight.source_frames[0]}`,
        { exact: true },
      );
      await expect(sourceImage).toBeVisible();
      await expect
        .poll(() =>
          sourceImage.evaluate(
            (element) => (element as HTMLImageElement).naturalWidth,
          ),
        )
        .toBeGreaterThan(0);
      await page.screenshot({ path: `test-results/${stem}-small-surface.png` });
      await evidence.click();
      await page
        .getByLabel("Scene editor", { exact: true })
        .evaluate((element) => {
          element.scrollTop = 0;
        });
    }
    const fittedOpening = result.scene!.objects.find(
      (o) => o.entrance && o.observed_geometry,
    );
    if (fittedOpening) {
      await page.getByLabel("Scene element").selectOption(fittedOpening.id);
      await expect(page.getByLabel("Selected object details")).toContainText(
        "RGB-D opening outline",
      );
      await expect(
        page.getByRole("button", { name: "Delete object", exact: true }),
      ).toBeDisabled();
      await page
        .getByLabel("Scene editor", { exact: true })
        .evaluate((element) => {
          element.scrollTop = 0;
        });
      await page.screenshot({ path: `test-results/${stem}-opening.png` });
      await page.getByLabel("Observed surfaces", { exact: true }).check();
      await expect
        .poll(async () => Number(await canvas.getAttribute("data-fps")))
        .toBeGreaterThan(0);
      await page.screenshot({
        path: `test-results/${stem}-opening-observed.png`,
      });
      await page.getByLabel("Observed surfaces", { exact: true }).uncheck();
    }
    const movable =
      result.scene!.objects.find(
        (o) =>
          o.movable &&
          o.provenance === "primitive_fitted" &&
          ["chair", "sofa", "table", "coffee table"].includes(o.kind),
      ) || result.scene!.objects.find((o) => o.movable)!;
    await page.getByLabel("Scene element").selectOption(movable.id);
    await expect(page.getByLabel("Selected object details")).toContainText(
      movable.label,
    );
    await page.screenshot({ path: `test-results/${stem}-modeler.png` });
    await page.getByRole("button", { name: "Move right", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Edits saved");
    await page.getByRole("button", { name: "Rotate 15°", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Edits saved");
    const exported = await request.get(`${API}/scans/${result.id}/export`);
    expect(exported.ok()).toBeTruthy();
    const bundle = await exported.json();
    expect(
      bundle.scan.scene.objects.find((o: { id: string }) => o.id === movable.id)
        .modified,
    ).toBe(true);
    const reloaded = await request.post(API + "/scans/import", {
      data: bundle,
    });
    expect(reloaded.ok()).toBeTruthy();
    const imported = await reloaded.json();
    expect(
      imported.scene.objects.find((o: { id: string }) => o.id === movable.id)
        .position,
    ).toEqual(
      bundle.scan.scene.objects.find((o: { id: string }) => o.id === movable.id)
        .position,
    );
    if (fittedOpening) {
      const opening = imported.scene.objects.find(
        (o: { id: string }) => o.id === fittedOpening.id,
      );
      expect(opening.geometry).toEqual(fittedOpening.geometry);
      expect(opening.observed_geometry).toEqual(
        fittedOpening.observed_geometry,
      );
      expect(opening.rotation).toEqual(fittedOpening.rotation);
      expect(opening.relationships).toEqual(fittedOpening.relationships);
    }
    await request.delete(`${API}/scans/${imported.id}`);
    await page
      .getByRole("button", { name: "Reset scene", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText(
      "Original reconstruction restored",
    );
    await page.getByRole("button", { name: "Close object editor" }).click();
    const beforeFrame = Number(await canvas.getAttribute("data-rendered"));
    await expect
      .poll(async () => Number(await canvas.getAttribute("data-rendered")))
      .toBeGreaterThan(beforeFrame + 100);
    await expect
      .poll(async () => Number(await canvas.getAttribute("data-fps")))
      .toBeGreaterThan(0);
    await page.screenshot({ path: `test-results/${stem}-geometry.png` });
    writeFileSync(
      `test-results/${stem}-browser-metrics.json`,
      JSON.stringify(
        {
          scan_id: result.id,
          fps: Number(await canvas.getAttribute("data-fps")),
          selected: movable.id,
          edited_export_reloaded: true,
          reset_verified: true,
        },
        null,
        2,
      ),
    );
  });
}
