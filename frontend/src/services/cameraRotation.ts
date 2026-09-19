export type CameraRotation = 0 | 90 | 180 | 270;

export function rotatedDimensions(width: number, height: number, rotation: CameraRotation): [number, number] {
  return rotation === 90 || rotation === 270 ? [height, width] : [width, height];
}

/** Draw the source around a center point, using the same clockwise turn for preview and inference. */
export function drawRotatedFrame(
  context: CanvasRenderingContext2D,
  source: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
  rotation: CameraRotation,
  centerX: number,
  centerY: number,
  scale: number,
) {
  context.save();
  context.translate(centerX, centerY);
  context.rotate(rotation * Math.PI / 180);
  context.drawImage(source, -sourceWidth * scale / 2, -sourceHeight * scale / 2,
    sourceWidth * scale, sourceHeight * scale);
  context.restore();
}
