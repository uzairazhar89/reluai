"""The models and variants the lab measures.

Each model is an ImageNet-1k classifier from the timm library (Apache 2.0), with weights
fetched from the library's GitHub releases and pinned by SHA-256. Each runs three ways:

* ``pytorch-fp32``: the model as trained, in PyTorch (eager mode, 32-bit floats);
* ``onnx-fp32``: exported to ONNX and run by ONNX Runtime, same 32-bit weights;
* ``onnx-int8``: the ONNX graph with weights and activations quantised to 8 bits (static,
  calibrated on real photos), run by ONNX Runtime.

ImageNet accuracy is quoted from timm's published results (not measured here: the
ImageNet validation images cannot be redistributed). What the lab measures is speed,
size and memory on this machine, and how often the faster variants agree with PyTorch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

Runtime = Literal["pytorch", "onnxruntime"]
TIMM_RESULTS = (
    "https://github.com/huggingface/pytorch-image-models/blob/"
    "af97f99efef62bd9bd7eaa908fffe5b7a2d98e2c/results/results-imagenet.csv"
)


@dataclass(frozen=True, slots=True)
class Weights:
    url: str
    sha256: str
    bytes: int

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    title: str
    timm_name: str
    summary: str
    params_millions: float
    input_size: int
    crop_pct: float
    interpolation: Literal["bicubic", "bilinear"]
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    weights: Weights
    published_top1: float
    published_top5: float
    paper: str
    licence: str = "Apache 2.0"
    homepage: str = ""

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["weights"]["filename"] = self.weights.filename
        return out


@dataclass(frozen=True, slots=True)
class VariantSpec:
    id: str
    title: str
    runtime: Runtime
    precision: Literal["fp32", "int8"]
    summary: str


IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="mobilenetv3-small",
        title="MobileNetV3-Small",
        timm_name="mobilenetv3_small_100.lamb_in1k",
        summary=(
            "A network designed for phones: depthwise-separable convolutions, "
            "squeeze-and-excitation blocks and hard-swish activations, 2.5 million parameters."
        ),
        params_millions=2.54,
        input_size=224,
        crop_pct=0.875,
        interpolation="bicubic",
        mean=IMAGENET_MEAN,
        std=IMAGENET_STD,
        weights=Weights(
            url=(
                "https://github.com/rwightman/pytorch-image-models/releases/download/"
                "v0.1-weights/mobilenetv3_small_100_lamb-266a294c.pth"
            ),
            sha256="266a294cbf3d119000a760bf5664a4d80a9674d0616b5cc0836b093d20c38249",
            bytes=10256237,
        ),
        published_top1=67.636,
        published_top5=87.638,
        paper="Howard et al. (2019), Searching for MobileNetV3. ICCV.",
        homepage="https://huggingface.co/timm/mobilenetv3_small_100.lamb_in1k",
    ),
    ModelSpec(
        id="resnet18",
        title="ResNet-18",
        timm_name="resnet18.a1_in1k",
        summary=(
            "A classic residual network built from plain 3×3 convolutions, 11.7 million "
            "parameters; trained with the 2021 'ResNet strikes back' recipe."
        ),
        params_millions=11.69,
        input_size=224,
        crop_pct=0.95,
        interpolation="bicubic",
        mean=IMAGENET_MEAN,
        std=IMAGENET_STD,
        weights=Weights(
            url=(
                "https://github.com/huggingface/pytorch-image-models/releases/download/"
                "v0.1-rsb-weights/resnet18_a1_0-d63eafa0.pth"
            ),
            sha256="d63eafa07a6e32a39d328e364f8c9f89d671444ecc7f02aa0f7eb8882af3dd29",
            bytes=46812648,
        ),
        published_top1=71.504,
        published_top5=90.086,
        paper=(
            "He et al. (2016), Deep Residual Learning for Image Recognition. CVPR; "
            "Wightman et al. (2021), ResNet strikes back."
        ),
        homepage="https://huggingface.co/timm/resnet18.a1_in1k",
    ),
)

VARIANTS: tuple[VariantSpec, ...] = (
    VariantSpec(
        "pytorch-fp32",
        "PyTorch FP32",
        "pytorch",
        "fp32",
        "The trained model in PyTorch, eager mode: the usual starting point.",
    ),
    VariantSpec(
        "onnx-fp32",
        "ONNX Runtime FP32",
        "onnxruntime",
        "fp32",
        "Exported to ONNX; the runtime fuses and reorders operations. Same weights.",
    ),
    VariantSpec(
        "onnx-int8",
        "ONNX Runtime INT8",
        "onnxruntime",
        "int8",
        "Weights and activations stored and computed as 8-bit integers, calibrated on photos.",
    ),
)
REFERENCE_VARIANT = "pytorch-fp32"


def model(model_id: str) -> ModelSpec:
    for m in MODELS:
        if m.id == model_id:
            return m
    raise KeyError(model_id)


def variant(variant_id: str) -> VariantSpec:
    for v in VARIANTS:
        if v.id == variant_id:
            return v
    raise KeyError(variant_id)
