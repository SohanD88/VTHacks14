import numpy as np
import pytest

from app.services.geometry import Fusion


def group(kind, points, frames, widths):
    return dict(
        kind=kind,
        instance=False,
        vertices=points,
        colors=[np.full_like(p, 0.5) for p in points],
        triangles=[np.empty((0, 3), int) for _ in points],
        frames=frames,
        scores=[0.9] * len(points),
        widths=widths,
        views=[dict(pose=np.eye(4), frame=f) for f in frames],
    )


@pytest.mark.parametrize("shared_frames", [True, False])
def test_disconnected_tables_use_their_own_width_evidence(shared_frames):
    # Two independently visible surfaces: 0.8 m and 1.6 m wide, 3 m apart.
    x, y = np.meshgrid(np.linspace(-0.4, 0.4, 17), np.linspace(-0.75, -0.6, 7))
    small = np.column_stack((x.ravel(), y.ravel(), np.full(x.size, 3.0)))
    large = small * [2, 1, 1] + [3, 0, 0]
    if shared_frames:
        points = [np.vstack([small, large])] * 3
        frames, widths = [1, 2, 3], [4.2] * 3
    else:
        points = [small] * 3 + [large] * 3
        frames, widths = list(range(6)), [0.8] * 3 + [1.6] * 3
    gx, gz = np.meshgrid(np.arange(12) * 0.1, np.arange(12) * 0.1 + 2)
    floor = np.column_stack((gx.ravel(), np.zeros(gx.size), gz.ravel()))
    fusion = Fusion({0: "table", 1: "floor"})
    fusion.camera, fusion.frames = [np.zeros(3)], [0]
    fusion.groups = [
        group("floor", [floor] * 3, [0, 1, 2], [1.1] * 3),
        group("table", points, frames, widths),
    ]
    scene, floor_found = fusion.finish()
    tables = sorted((o for o in scene.objects if o.kind == "table"), key=lambda o: o.position[0])
    assert floor_found and len(tables) == 2
    assert [o.size[0] for o in tables] == pytest.approx([0.8, 1.6])
    assert all(o.provenance == "primitive_fitted" for o in tables)
    assert [o.source_frames for o in tables] == (
        [[1, 2, 3], [1, 2, 3]] if shared_frames else [[0, 1, 2], [3, 4, 5]]
    )
