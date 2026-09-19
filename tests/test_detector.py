from types import SimpleNamespace

from PIL import Image

from app.detector import Detector


class FakeRFDETR:
    def predict(self, image, *, threshold, include_source_image):
        assert image.size == (200, 100)
        assert threshold == 0.5
        assert include_source_image is False
        return SimpleNamespace(
            xyxy=[[20, 10, 100, 80], [0, 0, 10, 10]],
            confidence=[0.91, 0.95],
            data={"class_name": ["cup", "__background__"]},
        )


def test_rfdetr_output_preserves_websocket_contract():
    detector = Detector()
    detector._model = FakeRFDETR()
    assert detector.detect(Image.new("RGB", (200, 100))) == [
        {"label": "cup", "confidence": 0.91, "box": [0.1, 0.1, 0.5, 0.8]}
    ]
