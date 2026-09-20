import { rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, resolve } from "node:path";

export default function teardown() {
  const directory = process.env.SPATIAL_E2E_DATA_DIR;
  if (
    directory &&
    resolve(dirname(directory)) === resolve(tmpdir()) &&
    basename(directory).startsWith("spatial-e2e-")
  )
    rmSync(directory, { recursive: true, force: true });
}
