import pytest

from socialoperator.types import CoordinateSpace, Point, Rect


def test_rect_center_contains_and_translate() -> None:
    rect = Rect(10, 20, 100, 40, CoordinateSpace.VIEWPORT)
    assert rect.center == Point(60, 40, CoordinateSpace.VIEWPORT)
    assert rect.contains(rect.center)
    assert rect.translate(5, -5) == Rect(15, 15, 100, 40, CoordinateSpace.VIEWPORT)


def test_rect_rejects_cross_space_point() -> None:
    rect = Rect(0, 0, 10, 10, CoordinateSpace.VIEWPORT)
    with pytest.raises(ValueError, match="same coordinate space"):
        rect.contains(Point(5, 5, CoordinateSpace.DESKTOP))


def test_rect_rejects_invalid_dimensions_and_scale() -> None:
    with pytest.raises(ValueError, match="positive"):
        Rect(0, 0, 0, 10, CoordinateSpace.VIEWPORT)
    with pytest.raises(ValueError, match="positive"):
        Rect(0, 0, 10, 10, CoordinateSpace.VIEWPORT).scale(0)
