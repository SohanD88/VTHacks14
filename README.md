# Live webcam object detection

A standalone browser demo and FastAPI service for detecting common objects in a webcam feed. The browser displays video locally and sends sampled JPEG frames to the server. The server returns COCO labels, confidence scores, and bounding boxes using the Apache-licensed RF-DETR Nano model. Frames are not saved.

## Run locally

Use Python 3.11–3.13. On macOS, grant your browser camera access when prompted.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and select **Start camera**. The official RF-DETR Nano checkpoint (about 349 MB) downloads into ignored `.model-cache/` on the first run. Later runs use the cache. Model warmup may take several seconds before the page shows READY. The page reports loading and connection errors.

The COCO model recognizes common categories such as person, bottle, cup, chair, book, laptop, and cell phone. It does not recognize arbitrary objects or infer 3D position. RF-DETR Nano has a higher published COCO box score than the previous SSDLite320 model, but individual objects can still be missed or mislabeled. Processing speed depends on the computer; the browser sends at most three frames per second and waits for each result before sending another.

## Website integration

The browser code in `static/app.js` can be adapted into your partner's website. The browser opens its own webcam with `getUserMedia`, shows the stream locally, and connects to `/ws/detect`. Browser camera access requires localhost or HTTPS. A deployed HTTPS site needs an HTTPS/WSS backend reachable by that site.

WebSocket protocol v1:

1. Server sends `{"type":"status","status":"loading"}`, then `{"type":"status","status":"ready"}`.
2. Client sends a JSON text message `{"type":"frame","id":1,"width":640,"height":480}`, immediately followed by the JPEG as one binary message. Dimensions describe the sent JPEG. Send the next pair only after receiving the preceding result.
3. Server replies `{"type":"detections","id":1,"width":640,"height":480,"detections":[{"label":"bottle","confidence":0.91,"box":[0.1,0.2,0.4,0.8]}]}`. Boxes are `[left, top, right, bottom]`, normalized to 0–1. An empty detections array is normal.
4. Invalid frames receive `{"type":"error","message":"..."}`. A model load failure sends an error then closes the connection. `GET /api/health` reports server and model state.

JPEGs are limited to 4 MB and dimensions to 4096 pixels per side. Set `DETECTION_CONFIDENCE` between 0 and 1 to change the default 0.5 threshold. A USB webcam on the same laptop works through the same browser API. A camera on another device will need a sender that uses this protocol or an ingest bridge.

## Checks

```bash
python -m pytest -q
```

Tests exercise the WebSocket contract with a stub detector, without downloading weights or requiring a webcam. To verify the real model, start the server and hold a supported object in front of the camera. Configure HTTPS and access control before exposing the API beyond your machine.

RF-DETR Nano is released under Apache 2.0. Pretrained weights and training data may have separate terms; review them before distributing a product.
