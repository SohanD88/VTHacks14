import { expect, test } from '@playwright/test';

test.use({ permissions: ['camera'], launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] } });

test('live camera uses JPEG protocol, overlays detections, survives navigation and stops', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let connections = 0, frames = 0;
  await page.routeWebSocket('**/api/camera/detect', socket => {
    connections++;
    socket.send(JSON.stringify({ type: 'status', status: 'loading' }));
    socket.send(JSON.stringify({ type: 'status', status: 'ready' }));
    let header: { id: number; width: number; height: number } | null = null;
    socket.onMessage(message => {
      if (typeof message === 'string') { header = JSON.parse(message); return; }
      expect(header).not.toBeNull();
      expect(header!.width).toBeLessThanOrEqual(640);
      expect(message[0]).toBe(0xff); expect(message[1]).toBe(0xd8);
      frames++;
      socket.send(JSON.stringify({ ...header, type: 'detections', processing_ms: 42, detections: [{ label: 'cup', confidence: .91, box: [.1, .2, .5, .8] }] }));
      header = null;
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Start camera', exact: true }).click();
  await expect(page.getByTestId('live-detections')).toContainText('cup');
  await expect(page.getByTestId('live-detections')).toContainText('91%');
  await expect(page.locator('.dashboard-view .detection-overlay')).toHaveAttribute('data-count', '1');
  await page.screenshot({ path: 'test-results/live-camera.png', fullPage: true });
  await page.getByRole('button', { name: 'Open the full 3D modeling environment' }).click();
  await expect(page.getByRole('button', { name: 'Stop camera', exact: true })).toBeVisible();
  await expect.poll(() => page.locator('.modeler-view video').evaluate((el: HTMLVideoElement) => el.videoWidth)).toBeGreaterThan(0);
  expect(connections).toBe(1);
  await page.getByRole('button', { name: 'Stop camera', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start camera', exact: true })).toBeVisible();
  await expect.poll(() => page.locator('.modeler-view video').evaluate((el: HTMLVideoElement) => el.srcObject)).toBeNull();
  await page.getByRole('button', { name: 'Return to dashboard' }).click();
  await expect(page.getByTestId('live-detections')).not.toContainText('cup');
  await page.getByRole('button', { name: 'Start camera', exact: true }).click();
  await expect(page.getByTestId('live-detections')).toContainText('cup');
  expect(connections).toBe(2); expect(frames).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test('camera permission failure is visible and can be retried', async ({ page }) => {
  await page.addInitScript(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Permission denied', 'NotAllowedError'); }; });
  await page.goto('/');
  await page.getByRole('button', { name: 'Start camera', exact: true }).click();
  await expect(page.locator('.dashboard-view .camera-message')).toContainText('Permission denied');
  await expect(page.getByRole('button', { name: 'Start camera', exact: true })).toBeEnabled();
});

test('model failure exposes retry and reconnect clears stale results', async ({ page }) => {
  let connections = 0;
  await page.routeWebSocket('**/api/camera/detect', socket => {
    connections++;
    if (connections === 1) {
      socket.send(JSON.stringify({ type: 'error', fatal: true, message: 'Model could not load' }));
      socket.close({ code: 1011 });
    } else if (connections === 2) {
      socket.send(JSON.stringify({ type: 'status', status: 'ready' }));
      socket.onMessage(message => { if (typeof message !== 'string') socket.close({ code: 1012 }); });
    } else socket.send(JSON.stringify({ type: 'status', status: 'ready' }));
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Start camera', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Retry detection' })).toBeVisible();
  await page.getByRole('button', { name: 'Retry detection' }).click();
  await expect.poll(() => connections).toBe(3);
  await expect(page.locator('.dashboard-view .camera-model-state')).toHaveText('ready');
});
