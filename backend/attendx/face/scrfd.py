# Vendored from VEIL-X (github.com/MeezaUni/VEIL-X, commit e37aef5, src/veilx/detect/scrfd.py).
# Unchanged except for import paths. MIT licence (VEIL-X code).
"""SCRFD face detector (InsightFace ``det_10g`` from the ``buffalo_l`` v0.7 release).

Inference follows InsightFace's reference ``SCRFD.detect``: the RGB image is resized (aspect
kept) into a zero-padded ``input_size`` canvas, normalised as ``(x - 127.5) / 128``; outputs
of the three strides (8, 16, 32; two anchors per location) give scores, box distances and
five-landmark offsets (all scaled by the stride); boxes above ``det_thresh`` are kept and
NMS-suppressed at ``nms_thresh``. Licence of the weights: InsightFace pretrained models are
for non-commercial research only.

The decoding helpers are numpy-only and unit-tested; ``SCRFDDetector`` needs onnxruntime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

F32 = NDArray[np.float32]
STRIDES = (8, 16, 32)
NUM_ANCHORS = 2


@dataclass(frozen=True)
class Detection:
    box: F32  # (4,) x1, y1, x2, y2 in original-image pixels
    score: float
    landmarks: F32  # (5, 2)


def anchor_centers(height: int, width: int, stride: int) -> F32:
    """(h*w*NUM_ANCHORS, 2) anchor centres (x, y) in input-canvas pixels, row-major."""
    ys, xs = np.mgrid[:height, :width]
    c = np.stack([xs, ys], axis=-1).astype(np.float32).reshape(-1, 2) * stride
    return np.repeat(c, NUM_ANCHORS, axis=0) if NUM_ANCHORS > 1 else c


def distance2bbox(centers: F32, dist: F32) -> F32:
    return np.stack(
        [
            centers[:, 0] - dist[:, 0],
            centers[:, 1] - dist[:, 1],
            centers[:, 0] + dist[:, 2],
            centers[:, 1] + dist[:, 3],
        ],
        axis=-1,
    )


def distance2kps(centers: F32, dist: F32) -> F32:
    out = np.empty_like(dist)
    out[:, 0::2] = centers[:, 0:1] + dist[:, 0::2]
    out[:, 1::2] = centers[:, 1:2] + dist[:, 1::2]
    return out


def nms(dets: F32, thresh: float) -> list[int]:
    """Greedy NMS on rows (x1, y1, x2, y2, score); returns kept indices by score."""
    x1, y1, x2, y2, s = (dets[:, k] for k in range(5))
    area = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = s.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        iou = inter / (area[i] + area[order[1:]] - inter)
        order = order[1:][iou <= thresh]
    return keep


def decode(
    outputs: list[NDArray[Any]], input_hw: tuple[int, int], det_thresh: float
) -> tuple[F32, F32, F32]:
    """Raw network outputs (scores x3, boxes x3, kps x3) -> (scores, boxes, kps) on the canvas."""
    scores, boxes, kpss = [], [], []
    h, w = input_hw
    for k, stride in enumerate(STRIDES):
        sc = outputs[k].reshape(-1)
        bb = outputs[k + 3].reshape(-1, 4) * stride
        kp = outputs[k + 6].reshape(-1, 10) * stride
        centers = anchor_centers(h // stride, w // stride, stride)
        pos = np.where(sc >= det_thresh)[0]
        scores.append(sc[pos])
        boxes.append(distance2bbox(centers, bb)[pos])
        kpss.append(distance2kps(centers, kp)[pos])
    return (
        np.concatenate(scores).astype(np.float32),
        np.concatenate(boxes).astype(np.float32),
        np.concatenate(kpss).astype(np.float32).reshape(-1, 5, 2),
    )


def select_central(dets: list[Detection], image_hw: tuple[int, int]) -> int | None:
    """Index of the detection whose box centre is closest to the image centre (LFW images are
    centred on the labelled person); ties -> higher score."""
    if not dets:
        return None
    cy, cx = image_hw[0] / 2.0, image_hw[1] / 2.0
    d = [
        (
            float(np.hypot((b.box[0] + b.box[2]) / 2 - cx, (b.box[1] + b.box[3]) / 2 - cy)),
            -b.score,
            i,
        )
        for i, b in enumerate(dets)
    ]
    return min(d)[2]


class SCRFDDetector:
    def __init__(
        self,
        model_path: Path,
        *,
        input_size: tuple[int, int] = (640, 640),
        det_thresh: float = 0.5,
        nms_thresh: float = 0.4,
        providers: tuple[str, ...] = ("CPUExecutionProvider",),
    ) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_path), opts, providers=list(providers))
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        if len(self.output_names) != 9:
            raise ValueError("expected an SCRFD model with keypoints (9 outputs)")
        self.input_size = input_size
        self.det_thresh = det_thresh
        self.nms_thresh = nms_thresh

    def detect(self, image_rgb: NDArray[np.uint8]) -> list[Detection]:
        import cv2

        ih, iw = image_rgb.shape[:2]
        tw, th = self.input_size
        if ih / iw > th / tw:
            nh, nw = th, int(th / (ih / iw))
        else:
            nw, nh = tw, int(tw * (ih / iw))
        scale = nh / ih
        canvas = np.zeros((th, tw, 3), dtype=np.uint8)
        canvas[:nh, :nw] = cv2.resize(image_rgb, (nw, nh))
        blob = ((canvas.astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None]
        outs = self.session.run(self.output_names, {self.input_name: blob})
        scores, boxes, kps = decode(outs, (th, tw), self.det_thresh)
        if scores.size == 0:
            return []
        boxes /= scale
        kps /= scale
        dets = np.hstack([boxes, scores[:, None]])
        keep = nms(dets, self.nms_thresh)
        return [Detection(boxes[i], float(scores[i]), kps[i]) for i in keep]
