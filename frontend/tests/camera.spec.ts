import { expect, test, type Page } from "@playwright/test";

test.use({
  permissions: ["camera"],
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
});

async function jpegQuadrants(page: Page, jpeg: Buffer) {
  return page.evaluate(async (encoded) => {
    const image = new Image();
    image.src = `data:image/jpeg;base64,${encoded}`;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d")!;
    context.drawImage(image, 0, 0);
    return [
      [0.25, 0.25],
      [0.75, 0.25],
      [0.25, 0.75],
      [0.75, 0.75],
    ].map(([x, y]) => {
      const [red, green, blue] = context.getImageData(
        x * canvas.width,
        y * canvas.height,
        1,
        1,
      ).data;
      if (red > 140 && green > 140) return "yellow";
      if (red > 140) return "red";
      if (green > 140) return "green";
      if (blue > 140) return "blue";
      return "unknown";
    });
  }, jpeg.toString("base64"));
}

test("live camera uses JPEG protocol, overlays detections, survives navigation and stops", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let connections = 0,
    frames = 0;
  const checkWebcamAlignment = async (rotation: 0 | 90) => {
    await expect
      .poll(() =>
        page.locator(".dashboard-view .live-stage").evaluate((stage, angle) => {
          const video = stage.querySelector("video")!;
          const canvas = stage.querySelector(
            ".detection-overlay",
          ) as HTMLCanvasElement;
          if (
            !video.videoWidth ||
            !video.videoHeight ||
            canvas.dataset.count !== "1"
          )
            return false;
          const bounds = stage.getBoundingClientRect();
          const quarterTurn = angle === 90;
          const sourceWidth = quarterTurn
            ? video.videoHeight
            : video.videoWidth;
          const sourceHeight = quarterTurn
            ? video.videoWidth
            : video.videoHeight;
          const fit = Math.min(
            bounds.width / sourceWidth,
            bounds.height / sourceHeight,
          );
          const width = sourceWidth * fit,
            height = sourceHeight * fit;
          const offsetX = (bounds.width - width) / 2,
            offsetY = (bounds.height - height) / 2;
          const sample = (x: number, y: number) =>
            canvas
              .getContext("2d")!
              .getImageData(
                Math.round((x * canvas.width) / bounds.width),
                Math.round((y * canvas.height) / bounds.height),
                1,
                1,
              ).data;
          const footage = sample(offsetX + width * 0.7, offsetY + height * 0.3);
          const border = sample(offsetX + width * 0.3, offsetY + height * 0.2);
          const margin = sample(offsetX / 2, bounds.height / 2);
          return (
            footage[3] > 200 &&
            footage[1] > 30 &&
            border[1] > 100 &&
            border[3] > 100 &&
            (offsetX < 4 || margin[3] === 0)
          );
        }, rotation),
      )
      .toBe(true);
  };
  await page.routeWebSocket("**/api/camera/detect", (socket) => {
    connections++;
    socket.send(JSON.stringify({ type: "status", status: "loading" }));
    socket.send(JSON.stringify({ type: "status", status: "ready" }));
    let header: { id: number; width: number; height: number } | null = null;
    socket.onMessage((message) => {
      if (typeof message === "string") {
        header = JSON.parse(message);
        return;
      }
      expect(header).not.toBeNull();
      expect(header!.width).toBeLessThanOrEqual(640);
      expect(message[0]).toBe(0xff);
      expect(message[1]).toBe(0xd8);
      frames++;
      socket.send(
        JSON.stringify({
          ...header,
          type: "detections",
          processing_ms: 42,
          detections: [
            { label: "cup", confidence: 0.91, box: [0.1, 0.2, 0.5, 0.8] },
          ],
        }),
      );
      header = null;
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await expect(page.getByTestId("live-detections")).toContainText("cup");
  await expect(page.getByTestId("live-detections")).toContainText("91%");
  await expect(
    page.locator(".dashboard-view .detection-overlay"),
  ).toHaveAttribute("data-count", "1");
  await checkWebcamAlignment(0);
  await page.getByRole("button", { name: "Rotate camera 90 degrees" }).click();
  await checkWebcamAlignment(90);
  await page.screenshot({
    path: "test-results/live-camera.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  await expect(
    page.getByRole("button", { name: "Stop camera", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".modeler-view video")
        .evaluate((el: HTMLVideoElement) => el.videoWidth),
    )
    .toBeGreaterThan(0);
  expect(connections).toBe(1);
  await page.getByRole("button", { name: "Stop camera", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Start camera", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator(".modeler-view video")
        .evaluate((el: HTMLVideoElement) => el.srcObject),
    )
    .toBeNull();
  await page.getByRole("button", { name: "Return to dashboard" }).click();
  await expect(page.getByTestId("live-detections")).not.toContainText("cup");
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await expect(page.getByTestId("live-detections")).toContainText("cup");
  expect(connections).toBe(2);
  expect(frames).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test("Rotate 90° turns browser webcam pixels and keeps boxes over the fitted preview", async ({
  page,
}) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 800;
      canvas.height = 600;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#ff0000";
      context.fillRect(0, 0, 400, 300);
      context.fillStyle = "#00ff00";
      context.fillRect(400, 0, 400, 300);
      context.fillStyle = "#0000ff";
      context.fillRect(0, 300, 400, 300);
      context.fillStyle = "#ffff00";
      context.fillRect(400, 300, 400, 300);
      (window as Window & { testCamera?: HTMLCanvasElement }).testCamera =
        canvas;
      return canvas.captureStream(15);
    };
  });
  let rotatedJpeg: Buffer | null = null;
  await page.routeWebSocket("**/api/camera/detect", (socket) => {
    socket.send(JSON.stringify({ type: "status", status: "ready" }));
    let header: { id: number; width: number; height: number } | null = null;
    socket.onMessage((message) => {
      if (typeof message === "string") {
        header = JSON.parse(message);
        return;
      }
      expect(header).not.toBeNull();
      if (header!.width === 480 && header!.height === 640)
        rotatedJpeg = Buffer.from(message);
      socket.send(
        JSON.stringify({
          ...header,
          type: "detections",
          processing_ms: 10,
          detections: [
            {
              label: "blue square",
              confidence: 0.99,
              box: [0.05, 0.05, 0.45, 0.45],
            },
          ],
        }),
      );
      header = null;
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await expect(page.getByTestId("live-detections")).toContainText(
    "blue square",
  );
  await page.getByRole("button", { name: "Rotate camera 90 degrees" }).click();
  await expect.poll(() => rotatedJpeg !== null).toBe(true);
  expect(await jpegQuadrants(page, rotatedJpeg!)).toEqual([
    "blue",
    "red",
    "yellow",
    "green",
  ]);
  const checkPreview = async () =>
    expect
      .poll(() =>
        page
          .locator(".dashboard-view .detection-overlay")
          .evaluate((canvasElement) => {
            const canvas = canvasElement as HTMLCanvasElement;
            const stage = canvas.parentElement!.getBoundingClientRect();
            const fit = Math.min(stage.width / 600, stage.height / 800);
            const width = 600 * fit,
              height = 800 * fit;
            const offsetX = (stage.width - width) / 2,
              offsetY = (stage.height - height) / 2;
            const sample = (x: number, y: number) => {
              const [red, green, blue, alpha] = canvas
                .getContext("2d")!
                .getImageData(
                  Math.round((x * canvas.width) / stage.width),
                  Math.round((y * canvas.height) / stage.height),
                  1,
                  1,
                ).data;
              if (alpha < 200) return "empty";
              if (red > 140 && green > 140) return "yellow";
              if (red > 140) return "red";
              if (green > 140 && blue < 140) return "green";
              if (blue > 140 && red < 140 && green < 140) return "blue";
              return "other";
            };
            const colors = [
              [0.25, 0.25],
              [0.75, 0.25],
              [0.25, 0.75],
              [0.75, 0.75],
            ].map(([x, y]) =>
              sample(offsetX + x * width, offsetY + y * height),
            );
            const edge = sample(
              offsetX + 0.25 * width,
              offsetY + 0.05 * height,
            );
            return (
              colors.join(",") === "blue,red,yellow,green" &&
              edge === "other" &&
              sample(offsetX / 2, stage.height / 2) === "empty"
            );
          }),
      )
      .toBe(true);
  await checkPreview();
  await page.setViewportSize({ width: 960, height: 700 });
  await checkPreview();
});

test("camera permission failure is visible and can be retried", async ({
  page,
}) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException("Permission denied", "NotAllowedError");
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await expect(page.locator(".dashboard-view .camera-message")).toContainText(
    "Permission denied",
  );
  await expect(
    page.getByRole("button", { name: "Start camera", exact: true }),
  ).toBeEnabled();
});

test("model failure exposes retry and reconnect clears stale results", async ({
  page,
}) => {
  let connections = 0;
  await page.routeWebSocket("**/api/camera/detect", (socket) => {
    connections++;
    if (connections === 1) {
      socket.send(
        JSON.stringify({
          type: "error",
          fatal: true,
          message: "Model could not load",
        }),
      );
      socket.close({ code: 1011 });
    } else if (connections === 2) {
      socket.send(JSON.stringify({ type: "status", status: "ready" }));
      socket.onMessage((message) => {
        if (typeof message !== "string") socket.close({ code: 1012 });
      });
    } else socket.send(JSON.stringify({ type: "status", status: "ready" }));
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Retry detection" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry detection" }).click();
  await expect.poll(() => connections).toBe(3);
  await expect(page.locator(".dashboard-view .camera-model-state")).toHaveText(
    "ready",
  );
});

test("webcam recording can be reviewed and submitted", async ({ page }) => {
  await page.routeWebSocket("**/api/camera/detect", (socket) => {
    socket.send(JSON.stringify({ type: "status", status: "ready" }));
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Start recording", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Start recording", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Stop recording", exact: true }),
  ).toBeEnabled();
  await page.waitForTimeout(1200); // Capture a nonempty recording, not a fake frame timer.
  await page
    .getByRole("button", { name: "Stop recording", exact: true })
    .click();
  await expect(page.locator(".uploaded-video")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reconstruct video", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".camera-panel")).not.toContainText(
    "Infinity seconds",
  );
  let submitted = false;
  await page.route("**/api/scans", (route) => {
    if (route.request().method() !== "POST") return route.continue();
    submitted = (route.request().postDataBuffer()?.length || 0) > 1000;
    return route.fulfill({
      status: 422,
      json: { error: { message: "Controlled capture validation response" } },
    });
  });
  await page
    .getByRole("button", { name: "Reconstruct video", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "Controlled capture validation response",
  );
  expect(submitted).toBe(true);
});

test("glasses stream detects objects, rotates in both views, and switches back to the computer", async ({
  page,
}) => {
  let snapshots = 0,
    connections = 0,
    label = "cup",
    glassesAvailable = true;
  const frameSizes: string[] = [];
  let rotatedJpeg: Buffer | null = null;
  await page.routeWebSocket("**/api/camera/detect", (socket) => {
    connections++;
    socket.send(JSON.stringify({ type: "status", status: "ready" }));
    let header: { id: number; width: number; height: number } | null = null;
    socket.onMessage((message) => {
      if (typeof message === "string") {
        header = JSON.parse(message);
        return;
      }
      expect(header).not.toBeNull();
      expect(header!.width).toBeLessThanOrEqual(640);
      expect(header!.height).toBeLessThanOrEqual(640);
      frameSizes.push(`${header!.width}x${header!.height}`);
      expect(message[0]).toBe(0xff);
      expect(message[1]).toBe(0xd8);
      if (
        header!.width === 480 &&
        header!.height === 640 &&
        rotatedJpeg === null
      )
        rotatedJpeg = Buffer.from(message);
      socket.send(
        JSON.stringify({
          ...header,
          type: "detections",
          processing_ms: 42,
          detections: [{ label, confidence: 0.91, box: [0.1, 0.2, 0.5, 0.8] }],
        }),
      );
      header = null;
    });
  });
  await page.goto("/");
  const jpeg = Buffer.from(
    (
      await page.evaluate(() => {
        const canvas = document.createElement("canvas");
        canvas.width = 800;
        canvas.height = 600;
        const context = canvas.getContext("2d")!;
        context.fillStyle = "#ff0000";
        context.fillRect(0, 0, 400, 300);
        context.fillStyle = "#00ff00";
        context.fillRect(400, 0, 400, 300);
        context.fillStyle = "#0000ff";
        context.fillRect(0, 300, 400, 300);
        context.fillStyle = "#ffff00";
        context.fillRect(400, 300, 400, 300);
        return canvas.toDataURL("image/jpeg");
      })
    ).split(",")[1],
    "base64",
  );
  await page.route("http://127.0.0.1:8080/**", async (route) => {
    if (route.request().url().includes("/frame.jpg")) snapshots++;
    if (!glassesAvailable) {
      await route.abort("failed");
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "image/jpeg",
      body: jpeg,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  });
  const dashboard = page.locator(".dashboard-view");
  await dashboard
    .getByRole("button", { name: "Start camera", exact: true })
    .click();
  await expect(page.getByTestId("live-detections")).toContainText("cup");
  label = "bottle";
  await dashboard.getByLabel("Camera source").selectOption("glasses");
  await expect(dashboard.locator(".glasses-video")).toBeVisible();
  await expect(page.getByTestId("live-detections")).toContainText("bottle");
  await expect(dashboard.locator(".detection-overlay")).toHaveAttribute(
    "data-count",
    "1",
  );
  expect(snapshots).toBeGreaterThan(0);
  await page.setViewportSize({ width: 900, height: 700 });
  await expect
    .poll(async () =>
      dashboard
        .locator(".detection-overlay")
        .evaluate((canvas: HTMLCanvasElement) => {
          const stage = canvas.parentElement!.getBoundingClientRect();
          const scale = canvas.width / stage.width;
          const fit = Math.min(stage.width / 800, stage.height / 600);
          const x = ((stage.width - 800 * fit) / 2 + 800 * fit * 0.3) * scale;
          const y = ((stage.height - 600 * fit) / 2 + 600 * fit * 0.2) * scale;
          const pixel = canvas
            .getContext("2d")!
            .getImageData(Math.round(x), Math.round(y), 1, 1).data;
          return pixel[1] > 100 && pixel[3] > 100;
        }),
    )
    .toBe(true);
  const rotate = dashboard.getByRole("button", {
    name: "Rotate camera 90 degrees",
  });
  frameSizes.length = 0;
  await rotate.click();
  await expect(rotate).toHaveAttribute("title", "Current rotation: 90°");
  await expect.poll(() => frameSizes.includes("480x640")).toBe(true);
  expect(rotatedJpeg).not.toBeNull();
  const quadrants = await jpegQuadrants(page, rotatedJpeg!);
  expect(quadrants).toEqual(["blue", "red", "yellow", "green"]);
  await expect
    .poll(async () =>
      dashboard
        .locator(".detection-overlay")
        .evaluate((canvas: HTMLCanvasElement) => {
          const stage = canvas.parentElement!.getBoundingClientRect();
          const preview = canvas
            .parentElement!.querySelector(".glasses-video")!
            .getBoundingClientRect();
          const fit = Math.min(stage.width / 600, stage.height / 800);
          const expectedWidth = 600 * fit,
            expectedHeight = 800 * fit;
          const scale = canvas.width / stage.width;
          const x =
            ((stage.width - expectedWidth) / 2 + expectedWidth * 0.3) * scale;
          const y =
            ((stage.height - expectedHeight) / 2 + expectedHeight * 0.2) *
            scale;
          const pixel = canvas
            .getContext("2d")!
            .getImageData(Math.round(x), Math.round(y), 1, 1).data;
          return (
            Math.abs(preview.width - expectedWidth) < 1 &&
            Math.abs(preview.height - expectedHeight) < 1 &&
            pixel[1] > 100 &&
            pixel[3] > 100
          );
        }),
    )
    .toBe(true);
  await dashboard
    .getByRole("button", { name: "Open the full 3D modeling environment" })
    .click();
  await expect(page.locator(".modeler-view .glasses-video")).toBeVisible();
  await expect(
    page.locator(".modeler-view .detection-overlay"),
  ).toHaveAttribute("data-count", "1");
  const modelerRotate = page
    .locator(".modeler-view")
    .getByRole("button", { name: "Rotate camera 90 degrees" });
  await expect(modelerRotate).toHaveAttribute("title", "Current rotation: 90°");
  frameSizes.length = 0;
  await modelerRotate.click();
  await expect.poll(() => frameSizes.includes("640x480")).toBe(true);
  await page.getByRole("button", { name: "Return to dashboard" }).click();
  await expect(rotate).toHaveAttribute("title", "Current rotation: 180°");
  frameSizes.length = 0;
  await rotate.click();
  await expect.poll(() => frameSizes.includes("480x640")).toBe(true);
  frameSizes.length = 0;
  await rotate.click();
  await expect.poll(() => frameSizes.includes("640x480")).toBe(true);
  await rotate.click();
  await expect(rotate).toHaveAttribute("title", "Current rotation: 90°");
  glassesAvailable = false;
  await expect(dashboard.locator(".camera-message")).toContainText(
    "Cannot read the glasses camera",
  );
  await expect(dashboard.locator(".detection-overlay")).toHaveAttribute(
    "data-count",
    "0",
  );
  label = "cup";
  frameSizes.length = 0;
  await dashboard.getByLabel("Camera source").selectOption("computer");
  await expect(dashboard.locator(".glasses-video")).toHaveCount(0);
  await expect(page.getByTestId("live-detections")).toContainText("cup");
  await expect(rotate).toHaveAttribute("title", "Current rotation: 90°");
  await expect
    .poll(() =>
      frameSizes.some((size) => {
        const [width, height] = size.split("x").map(Number);
        return width < height;
      }),
    )
    .toBe(true);
  expect(connections).toBe(3);
  await dashboard
    .getByRole("button", { name: "Stop camera", exact: true })
    .click();
  const stoppedAt = snapshots;
  await page.waitForTimeout(700);
  expect(snapshots).toBe(stoppedAt);
});

test("unavailable glasses stream reports an error and the saved address survives reload", async ({
  page,
}) => {
  await page.route("http://127.0.0.1:8080/**", (route) =>
    route.abort("failed"),
  );
  await page.routeWebSocket("**/api/camera/detect", (socket) => {
    socket.send(JSON.stringify({ type: "status", status: "ready" }));
  });
  await page.goto("/");
  const dashboard = page.locator(".dashboard-view");
  await dashboard.getByLabel("Camera source").selectOption("glasses");
  await dashboard
    .getByLabel("Glasses stream address")
    .fill("http://127.0.0.1:8080/stream");
  await dashboard
    .getByRole("button", { name: "Start camera", exact: true })
    .click();
  await expect(dashboard.locator(".camera-message")).toContainText(
    /Glasses stream unavailable|Cannot read the glasses camera/,
  );
  await expect(
    dashboard.getByRole("button", { name: "Retry detection" }),
  ).toBeVisible();
  await dashboard.getByLabel("Camera source").selectOption("computer");
  await expect(dashboard.locator(".camera-message")).not.toContainText(
    "Glasses stream unavailable",
  );
  await page.reload();
  await dashboard.getByLabel("Camera source").selectOption("glasses");
  await expect(dashboard.getByLabel("Glasses stream address")).toHaveValue(
    "http://127.0.0.1:8080/stream",
  );
});

test("immediately stopped recording stays local and explains minimum length", async ({
  page,
}) => {
  await page.routeWebSocket("**/api/camera/detect", (socket) => {
    socket.send(JSON.stringify({ type: "status", status: "ready" }));
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await page
    .getByRole("button", { name: "Start recording", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Stop recording", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Recording is too short");
  await expect(
    page.getByRole("button", { name: "Retry reconstruction", exact: true }),
  ).toBeDisabled();
});
