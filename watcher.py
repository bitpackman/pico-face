#!/usr/bin/env python3
"""pi-face presence watcher — IMX500 on-sensor person detection.

Privacy: no frames are ever stored or transmitted. Detection runs on the
camera sensor's own NPU; only {present, count, cx} numbers are POSTed to
the local pi-face server.
"""
import json
import time
import urllib.request

from picamera2 import Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import NetworkIntrinsics

MODEL = "/usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk"
SCORE_MIN = 0.55
POST_URL = "http://127.0.0.1:8090/presence"
POST_EVERY = 1.0


def main():
    imx500 = IMX500(MODEL)
    intrinsics = imx500.network_intrinsics or NetworkIntrinsics()
    labels = intrinsics.labels or []
    person_ids = {i for i, l in enumerate(labels) if str(l).lower() == "person"} or {0}
    input_w, input_h = imx500.get_input_size()

    picam2 = Picamera2(imx500.camera_num)
    config = picam2.create_preview_configuration(
        controls={"FrameRate": intrinsics.inference_rate or 10},
        buffer_count=12,
    )
    imx500.show_network_fw_progress_bar()  # first upload to sensor takes a while
    picam2.start(config)
    print("watcher: camera started")

    last_post = 0.0
    while True:
        md = picam2.capture_metadata()
        outputs = imx500.get_outputs(md, add_batch=True)
        present, count, cx, best = False, 0, 0.5, 0.0
        if outputs is not None and len(outputs) >= 3:
            boxes, scores, classes = outputs[0][0], outputs[1][0], outputs[2][0]
            if intrinsics.bbox_normalization:
                boxes = boxes / input_h
            if intrinsics.bbox_order == "xy":
                boxes = boxes[:, [1, 0, 3, 2]]
            for box, score, cls in zip(boxes, scores, classes):
                if score >= SCORE_MIN and int(cls) in person_ids:
                    count += 1
                    y0, x0, y1, x1 = [float(v) for v in box]
                    area = max(0.0, y1 - y0) * max(0.0, x1 - x0)
                    if area > best:
                        best, cx = area, (x0 + x1) / 2
            present = count > 0

        now = time.time()
        if now - last_post >= POST_EVERY:
            last_post = now
            try:
                data = json.dumps(
                    {"present": present, "count": count, "cx": round(cx, 3)}
                ).encode()
                req = urllib.request.Request(
                    POST_URL, data=data, headers={"Content-Type": "application/json"}
                )
                urllib.request.urlopen(req, timeout=2).read()
            except OSError:
                pass  # server down; keep watching


if __name__ == "__main__":
    while True:  # camera/model hiccups: retry forever
        try:
            main()
        except Exception as e:
            print(f"watcher error: {type(e).__name__}: {e}; retrying in 10s")
            time.sleep(10)
