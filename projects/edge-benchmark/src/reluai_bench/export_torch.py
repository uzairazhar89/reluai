"""Export a model to ONNX (runs in the PyTorch environment at image build time).

    <torch python> … reluai_bench.export_torch --model '<spec json>' --weights W --out F.onnx

Loads the timm architecture with the pinned weights and exports it with PyTorch's current
exporter (``torch.export`` graph capture, ``dynamo=True``) with a dynamic batch size, as a
single self-contained file. Optionally writes the 1,000 ImageNet class names. Prints one
JSON line with the versions used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="model spec as JSON")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--labels-out", type=Path, default=None)
    parser.add_argument("--opset", type=int, default=18)
    args = parser.parse_args(argv)
    spec = json.loads(args.model)

    import timm
    import torch
    from timm.data import ImageNetInfo

    torch.manual_seed(0)
    net = timm.create_model(spec["timm_name"], pretrained=False)
    net.load_state_dict(torch.load(args.weights, map_location="cpu", weights_only=True))
    net.eval()
    size = int(spec["input_size"])
    example = torch.zeros(1, 3, size, size)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        net,
        (example,),
        str(args.out),
        dynamo=True,
        external_data=False,
        opset_version=args.opset,
        input_names=["input"],
        output_names=["logits"],
        dynamic_shapes={"x": {0: torch.export.Dim("batch", min=1, max=64)}},
        verbose=False,
    )
    if args.labels_out:
        info = ImageNetInfo()
        names = [info.index_to_description(i).split(",")[0] for i in range(info.num_classes())]
        args.labels_out.write_text(json.dumps(names, indent=0), encoding="utf-8")
    print(
        json.dumps(
            {
                "torch": torch.__version__.split("+")[0],
                "timm": timm.__version__,
                "opset": args.opset,
                "exporter": "torch.onnx.export(dynamo=True)",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
