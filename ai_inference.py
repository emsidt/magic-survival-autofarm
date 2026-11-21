"""Local Inference Engine for Kaggle-trained Magic Survival AI models.

Supports two model families without requiring PyTorch on the local machine:
1. Skill Selection Value Network (`ai_models/skill_value_net.json`):
   - Pure NumPy MLP forward pass (< 0.1ms per card) predicting expected survival value Q(s, a).
2. Computer Vision CNNs (`ai_models/card_vision.onnx`, `ai_models/screen_vision.onnx`):
   - Executed via OpenCV's built-in `cv2.dnn.readNetFromONNX` (< 2ms on CPU).
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "ai_models"

# Canonical fusion pairs so the feature extractor knows if a candidate completes an active fusion
FUSION_PARTNERS: dict[str, set[str]] = {
    "spirit": {"electric_shock", "energy_bolt", "magic_bolt"},
    "electric_shock": {"spirit", "electric_zone", "thunderstorm"},
    "cyclone": {"satellite", "electric_zone", "blizzard"},
    "satellite": {"cyclone", "lava_zone", "meteor"},
    "magic_circle": {"intelligence", "cloaking", "arcane_ray"},
    "intelligence": {"magic_circle"},
    "blizzard": {"frost_nova", "cyclone", "incineration"},
    "frost_nova": {"blizzard", "tsunami", "meteor"},
    "tsunami": {"frost_nova", "arcane_ray"},
    "arcane_ray": {"magic_circle", "tsunami", "flash_shock"},
    "flash_shock": {"arcane_ray", "spirit", "armageddon"},
    "electric_zone": {"electric_shock", "cyclone", "lava_zone"},
}


def crop_card_slots(frame: np.ndarray, num_cards: int = 3) -> dict[int, np.ndarray]:
    """Crop the 3 or 4 card regions from a 9:16 portrait gameplay frame."""
    if frame is None or frame.size == 0:
        return {}
    h, w = frame.shape[:2]
    if num_cards == 4:
        bands = {
            1: (int(h * 0.18), int(h * 0.35)),
            2: (int(h * 0.35), int(h * 0.52)),
            3: (int(h * 0.52), int(h * 0.69)),
            4: (int(h * 0.69), int(h * 0.86)),
        }
    else:
        bands = {
            1: (int(h * 0.28), int(h * 0.44)),
            2: (int(h * 0.44), int(h * 0.58)),
            3: (int(h * 0.58), int(h * 0.74)),
        }
    x0, x1 = int(w * 0.10), int(w * 0.90)
    crops: dict[int, np.ndarray] = {}
    for idx, (y0, y1) in bands.items():
        roi = frame[y0:y1, x0:x1]
        if roi.size > 0:
            crops[idx] = roi
    return crops


def build_skill_feature_vector(
    vocab: list[str],
    skill_to_idx: dict[str, int],
    candidate_skill: str,
    active_skills: Optional[set[str]] = None,
    skill_levels: Optional[dict[str, int]] = None,
    level_count: int = 1,
    offered_level: Optional[int] = None,
    has_asterisk: bool = False,
) -> np.ndarray:
    """Construct the fixed-length feature vector for (state, candidate_action).
    Dimension = 2 * len(vocab) + 6:
      [0 .. V-1]       : Active skill level ratios (level / 7.0, or 0.35 if active with unknown level)
      [V .. 2V-1]      : One-hot encoding of candidate_skill
      [2V + 0]         : Normalized player level / step (min(1.0, level_count / 100.0))
      [2V + 1]         : Active skill count ratio (min(1.0, len(active_skills) / 15.0))
      [2V + 2]         : Candidate current level ratio (curr_level / 7.0)
      [2V + 3]         : Is level 7 mastery upgrade (1.0 if offered_level == 7 else 0.0)
      [2V + 4]         : Has asterisk / special star (1.0 if has_asterisk else 0.0)
      [2V + 5]         : Has active fusion partner in active_skills (1.0 or 0.0)
    """
    v_len = len(vocab)
    feat = np.zeros(2 * v_len + 6, dtype=np.float32)
    active_set = set(active_skills or ())
    levels_map = skill_levels or {}

    for sk in active_set:
        idx = skill_to_idx.get(sk)
        if idx is not None:
            lvl = levels_map.get(sk, 2)
            feat[idx] = min(1.0, float(lvl) / 7.0)

    cand_idx = skill_to_idx.get(candidate_skill)
    if cand_idx is not None:
        feat[v_len + cand_idx] = 1.0

    curr_lvl = levels_map.get(candidate_skill, 1 if candidate_skill in active_set else 0)
    eff_offered = offered_level if offered_level is not None else (curr_lvl + 1)
    partners = FUSION_PARTNERS.get(candidate_skill, set())
    has_partner = 1.0 if (partners and (partners & active_set)) else 0.0

    base = 2 * v_len
    feat[base + 0] = min(1.0, max(0.0, float(level_count) / 100.0))
    feat[base + 1] = min(1.0, float(len(active_set)) / 15.0)
    feat[base + 2] = min(1.0, float(curr_lvl) / 7.0)
    feat[base + 3] = 1.0 if eff_offered == 7 else 0.0
    feat[base + 4] = 1.0 if has_asterisk else 0.0
    feat[base + 5] = has_partner
    return feat


def _numpy_conv2d_s2_p1_relu(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """Fast pure-NumPy 3x3 Conv2d with stride=2, padding=1, followed by ReLU.
    x: (C_in, H, W) float32
    weight: (C_out, C_in, 3, 3) float32 (fused Conv+BN)
    bias: (C_out,) float32
    Returns: (C_out, H//2, W//2) float32
    """
    c_in, h, w = x.shape
    c_out = weight.shape[0]
    padded = np.pad(x, ((0, 0), (1, 1), (1, 1)), mode="constant", constant_values=0.0)
    windows = np.lib.stride_tricks.sliding_window_view(padded, (c_in, 3, 3))[0, ::2, ::2]
    out_h, out_w = windows.shape[:2]
    cols = np.ascontiguousarray(windows).reshape(out_h * out_w, c_in * 9)
    w_mat = weight.reshape(c_out, c_in * 9).T
    out = cols @ w_mat + bias
    np.maximum(out, 0.0, out=out)
    return out.T.reshape(c_out, out_h, out_w)


def _run_numpy_cnn(img_bgr: np.ndarray, size_wh: tuple[int, int], npz_weights: dict[str, np.ndarray]) -> np.ndarray:
    """Run 4-block fused TinyVisionCNN in pure NumPy (~1ms on CPU)."""
    resized = cv2.resize(img_bgr, size_wh, interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    x = np.transpose(rgb, (2, 0, 1))  # (3, H, W)
    for i in range(4):
        x = _numpy_conv2d_s2_p1_relu(x, npz_weights[f"w{i}"], npz_weights[f"b{i}"])
    pooled = x.mean(axis=(1, 2))  # AdaptiveAvgPool2d((1, 1)) -> (128,)
    logits = pooled @ npz_weights["fc_w"].T + npz_weights["fc_b"]
    return logits


class AIInferenceEngine:
    """Loads and runs Kaggle-trained skill selection and computer vision models."""

    def __init__(self, models_dir: Path = MODELS_DIR):
        self.models_dir = Path(models_dir)
        self.skill_net_data: Optional[dict[str, Any]] = None
        self.vocab: list[str] = []
        self.skill_to_idx: dict[str, int] = {}
        self.mlp_layers: list[tuple[np.ndarray, np.ndarray]] = []

        self.card_net: Any = None
        self.screen_net: Any = None
        self.card_npz: Optional[dict[str, np.ndarray]] = None
        self.screen_npz: Optional[dict[str, np.ndarray]] = None
        self.card_classes: list[str] = []
        self.screen_classes: list[str] = []
        self.card_input_size: tuple[int, int] = (192, 64)   # (W, H)
        self.screen_input_size: tuple[int, int] = (96, 160)  # (W, H)

        self.reload_models()

    def reload_models(self) -> None:
        """Load or reload exported model files if present in `ai_models/`."""
        self._load_skill_value_net()
        self._load_vision_nets()

    def _load_skill_value_net(self) -> None:
        net_path = self.models_dir / "skill_value_net.json"
        if not net_path.is_file():
            return
        try:
            data = json.loads(net_path.read_text(encoding="utf-8"))
            vocab = data.get("vocab", [])
            layers_raw = data.get("layers", [])
            if not isinstance(vocab, list) or not vocab or not layers_raw:
                return
            parsed_layers: list[tuple[np.ndarray, np.ndarray]] = []
            for layer in layers_raw:
                w = np.asarray(layer["weight"], dtype=np.float32)
                b = np.asarray(layer["bias"], dtype=np.float32)
                parsed_layers.append((w, b))
            self.vocab = [str(s) for s in vocab]
            self.skill_to_idx = {s: i for i, s in enumerate(self.vocab)}
            self.mlp_layers = parsed_layers
            self.skill_net_data = data
        except Exception:
            logging.exception("Failed to load skill_value_net.json")

    def _load_vision_nets(self) -> None:
        meta_path = self.models_dir / "vision_meta.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                self.card_classes = [str(c) for c in meta.get("card_classes", [])]
                self.screen_classes = [str(c) for c in meta.get("screen_classes", [])]
                if "card_size_wh" in meta and len(meta["card_size_wh"]) == 2:
                    self.card_input_size = (int(meta["card_size_wh"][0]), int(meta["card_size_wh"][1]))
                if "screen_size_wh" in meta and len(meta["screen_size_wh"]) == 2:
                    self.screen_input_size = (int(meta["screen_size_wh"][0]), int(meta["screen_size_wh"][1]))
            except Exception:
                logging.exception("Failed to read vision_meta.json")

        card_npz_path = self.models_dir / "card_vision.npz"
        if card_npz_path.is_file() and self.card_classes:
            try:
                with np.load(str(card_npz_path)) as data:
                    self.card_npz = {k: np.asarray(data[k], dtype=np.float32) for k in data.files}
            except Exception:
                logging.exception("Failed to load card_vision.npz")
                self.card_npz = None

        screen_npz_path = self.models_dir / "screen_vision.npz"
        if screen_npz_path.is_file() and self.screen_classes:
            try:
                with np.load(str(screen_npz_path)) as data:
                    self.screen_npz = {k: np.asarray(data[k], dtype=np.float32) for k in data.files}
            except Exception:
                logging.exception("Failed to load screen_vision.npz")
                self.screen_npz = None

        card_onnx = self.models_dir / "card_vision.onnx"
        if card_onnx.is_file() and self.card_classes and self.card_npz is None:
            try:
                self.card_net = cv2.dnn.readNetFromONNX(str(card_onnx))
            except Exception:
                logging.exception("Failed to load card_vision.onnx")
                self.card_net = None

        screen_onnx = self.models_dir / "screen_vision.onnx"
        if screen_onnx.is_file() and self.screen_classes and self.screen_npz is None:
            try:
                self.screen_net = cv2.dnn.readNetFromONNX(str(screen_onnx))
            except Exception:
                logging.exception("Failed to load screen_vision.onnx")
                self.screen_net = None

    @property
    def has_skill_model(self) -> bool:
        return bool(self.mlp_layers and self.vocab)

    @property
    def has_card_vision(self) -> bool:
        return (self.card_npz is not None or self.card_net is not None) and bool(self.card_classes)

    @property
    def has_screen_vision(self) -> bool:
        return (self.screen_npz is not None or self.screen_net is not None) and bool(self.screen_classes)

    def score_skill_candidate(
        self,
        skill_key: str,
        active_skills: Optional[set[str]] = None,
        skill_levels: Optional[dict[str, int]] = None,
        level_count: int = 1,
        offered_level: Optional[int] = None,
        has_asterisk: bool = False,
    ) -> float:
        """Predict expected survival utility score for picking `skill_key` in the current state.
        Returns a score roughly in [-10.0, +40.0] (or 0.0 if no trained model is loaded).
        """
        if not self.has_skill_model:
            return 0.0
        try:
            x = build_skill_feature_vector(
                self.vocab,
                self.skill_to_idx,
                skill_key,
                active_skills=active_skills,
                skill_levels=skill_levels,
                level_count=level_count,
                offered_level=offered_level,
                has_asterisk=has_asterisk,
            )
            h = x
            for i, (w, b) in enumerate(self.mlp_layers):
                # Linear layer: PyTorch stores weights as (out_features, in_features)
                h = h @ w.T + b
                # ReLU activation on all hidden layers except final output layer
                if i < len(self.mlp_layers) - 1:
                    h = np.maximum(0.0, h)
            val = float(np.squeeze(h))
            if not math.isfinite(val):
                return 0.0
            return val
        except Exception:
            return 0.0

    def predict_card_skills(
        self,
        frame: np.ndarray,
        num_cards: int = 3,
        min_conf: float = 0.72,
    ) -> dict[int, tuple[str, float]]:
        """Run `card_vision.npz` (or `.onnx`) on each card slot crop and return {slot_idx: (skill_key, confidence)}."""
        if not self.has_card_vision:
            return {}
        crops = crop_card_slots(frame, num_cards=num_cards)
        if not crops:
            return {}
        results: dict[int, tuple[str, float]] = {}
        target_w, target_h = self.card_input_size
        try:
            for idx, crop in crops.items():
                if self.card_npz is not None:
                    logits = _run_numpy_cnn(crop, (target_w, target_h), self.card_npz)
                else:
                    blob = cv2.dnn.blobFromImage(
                        crop,
                        scalefactor=1.0 / 255.0,
                        size=(target_w, target_h),
                        mean=(0.0, 0.0, 0.0),
                        swapRB=True,
                        crop=False,
                    )
                    self.card_net.setInput(blob)
                    logits = self.card_net.forward().flatten()
                if logits.size != len(self.card_classes):
                    continue
                exp_l = np.exp(logits - np.max(logits))
                probs = exp_l / np.sum(exp_l)
                best_i = int(np.argmax(probs))
                conf = float(probs[best_i])
                label = self.card_classes[best_i]
                if conf >= min_conf and label not in ("unknown", "none", ""):
                    results[idx] = (label, round(conf, 4))
        except Exception:
            pass
        return results

    def predict_screen_type(
        self,
        frame: np.ndarray,
        min_conf: float = 0.75,
    ) -> Optional[tuple[str, float]]:
        """Run `screen_vision.npz` (or `.onnx`) on the full frame and return (screen_type, confidence)."""
        if not self.has_screen_vision or frame is None or frame.size == 0:
            return None
        target_w, target_h = self.screen_input_size
        try:
            if self.screen_npz is not None:
                logits = _run_numpy_cnn(frame, (target_w, target_h), self.screen_npz)
            else:
                blob = cv2.dnn.blobFromImage(
                    frame,
                    scalefactor=1.0 / 255.0,
                    size=(target_w, target_h),
                    mean=(0.0, 0.0, 0.0),
                    swapRB=True,
                    crop=False,
                )
                self.screen_net.setInput(blob)
                logits = self.screen_net.forward().flatten()
            if logits.size != len(self.screen_classes):
                return None
            exp_l = np.exp(logits - np.max(logits))
            probs = exp_l / np.sum(exp_l)
            best_i = int(np.argmax(probs))
            conf = float(probs[best_i])
            if conf >= min_conf:
                return (self.screen_classes[best_i], round(conf, 4))
        except Exception:
            pass
        return None


_GLOBAL_AI_ENGINE: Optional[AIInferenceEngine] = None


def get_ai_engine() -> AIInferenceEngine:
    global _GLOBAL_AI_ENGINE
    if _GLOBAL_AI_ENGINE is None:
        _GLOBAL_AI_ENGINE = AIInferenceEngine()
    return _GLOBAL_AI_ENGINE
