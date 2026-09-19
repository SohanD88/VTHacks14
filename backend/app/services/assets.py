"""Evidence-scaled composite furniture meshes; explicitly primitive_fitted, never measured."""

import numpy as np

from app.schemas import Geometry


def furniture(kind, size, color):
    vertices, triangles, colors = [], [], []

    def box(center, dimensions):
        offset = len(vertices)
        x, y, z = np.array(dimensions) / 2
        base = (
            np.array(
                [
                    [-x, -y, -z],
                    [x, -y, -z],
                    [x, y, -z],
                    [-x, y, -z],
                    [-x, -y, z],
                    [x, -y, z],
                    [x, y, z],
                    [-x, y, z],
                ]
            )
            + center
        )
        vertices.extend(base.tolist())
        colors.extend([color] * 8)
        faces = [
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
            (0, 1, 5),
            (0, 5, 4),
            (3, 7, 6),
            (3, 6, 2),
            (0, 4, 7),
            (0, 7, 3),
            (1, 2, 6),
            (1, 6, 5),
        ]
        triangles.extend([[a + offset, b + offset, c + offset] for a, b, c in faces])

    def cylinder(center, radius_x, radius_z, height):
        offset = len(vertices)
        segments = 32
        for y in [-height / 2, height / 2]:
            for i in range(segments):
                t = i * 2 * np.pi / segments
                vertices.append(
                    [
                        center[0] + radius_x * np.cos(t),
                        center[1] + y,
                        center[2] + radius_z * np.sin(t),
                    ]
                )
                colors.append(color)
        for i in range(segments):
            j = (i + 1) % segments
            triangles.extend(
                [
                    [offset + i, offset + j, offset + segments + i],
                    [offset + j, offset + segments + j, offset + segments + i],
                ]
            )
        for i in range(1, segments - 1):
            triangles.extend(
                [
                    [offset, offset + i + 1, offset + i],
                    [offset + segments, offset + segments + i, offset + segments + i + 1],
                ]
            )

    w, h, d = size
    if kind == "sofa":
        box([0, -h * 0.15, 0], [w * 0.94, h * 0.32, d * 0.9])
        box([0, h * 0.18, -d * 0.4], [w, h * 0.62, d * 0.2])
        for x in [-1, 1]:
            box([x * w * 0.46, 0, 0], [w * 0.08, h * 0.58, d])
        for x in [-1, 1]:
            for z in [-1, 1]:
                box([x * w * 0.38, -h * 0.43, z * d * 0.3], [0.055, h * 0.14, 0.055])
        # Seat cushions preserve a sofa-like silhouette from all viewing angles.
        seats = max(1, round(w / 0.65))
        for i in range(seats):
            box(
                [(i - (seats - 1) / 2) * w * 0.82 / seats, -h * 0.005, d * 0.04],
                [w * 0.8 / seats, h * 0.08, d * 0.65],
            )
    elif kind == "chair":
        box([0, -h * 0.02, 0], [w, h * 0.09, d * 0.9])
        box([0, h * 0.24, -d * 0.43], [w * 0.92, h * 0.48, d * 0.09])
        for x in [-1, 1]:
            for z in [-1, 1]:
                box([x * w * 0.38, -h * 0.27, z * d * 0.34], [0.035, h * 0.46, 0.035])
    elif kind == "table":
        cylinder([0, h * 0.44, 0], w / 2, d / 2, h * 0.12)
        cylinder([0, -h * 0.03, 0], min(w, d) * 0.055, min(w, d) * 0.055, h * 0.82)
        cylinder([0, -h * 0.46, 0], w * 0.28, d * 0.28, h * 0.08)
    return Geometry(vertices=vertices, colors=colors, triangles=triangles)
