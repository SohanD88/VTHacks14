"""Deterministic logical grouping shared by Blender export and regular Python tests."""

from collections import Counter, defaultdict

PRIMARY = (
    "elevator",
    "door",
    "sofa",
    "table",
    "chair",
    "cabinet",
    "shelf",
    "plant",
    "book",
    "wall",
    "floor",
    "ceiling",
    "light",
    "windowpane",
    "fixture",
)
SURFACES = {"wall", "floor", "ceiling"}


def partition_group(parts):
    """Accessories inherit their assembly kind; surfaces and visibility never collapse."""
    counts = Counter(p["kind"] for p in parts)
    primary = next((k for k in PRIMARY if k in counts), sorted(counts)[0])
    buckets = defaultdict(list)
    for part in parts:
        kind = part["kind"] if part["kind"] in SURFACES else primary
        buckets[(kind, part["hidden"])].append(part)
    result = []
    for (kind, hidden), members in sorted(buckets.items()):
        result.append(
            dict(
                kind=kind,
                hidden=hidden,
                parts=members,
                frames=sorted({f for p in members for f in p["frames"]}),
                suffix=f" [{kind} {'cutaway' if hidden else 'visible'}]"
                if len(buckets) > 1
                else "",
                id=members[0]["id"] if len(buckets) == 1 else None,
            )
        )
    return result
