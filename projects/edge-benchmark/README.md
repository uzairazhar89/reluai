# Edge AI Benchmark Lab

The same image classifier three ways, measured on the server that serves this site:

| Variant | What it is |
| --- | --- |
| PyTorch FP32 | The model as trained, PyTorch eager mode |
| ONNX Runtime FP32 | Exported to ONNX; same 32-bit weights, fused graph |
| ONNX Runtime INT8 | Weights and activations in 8 bits (static, calibrated on photos) |

for two ImageNet classifiers of very different design: MobileNetV3-Small (depthwise
convolutions, squeeze-and-excitation, hard-swish; 2.5 M parameters) and ResNet-18 (plain
3×3 convolutions; 11.7 M), both from timm with weights pinned by SHA-256. Live demo and
results: <https://reluai.cloud/projects/edge-ai-benchmark-lab>.

## What is measured

Each model × variant × thread count (1 and 2) runs in a **fresh child process**, so memory,
thread pools and caches are its own:

- latency per photo at batch size 1, split into preprocessing (decode, resize, normalise),
  inference and postprocessing (softmax, top 5): median, 95th percentile, mean, minimum,
  after warm-up runs;
- CPU use while timing (CPU time over wall time; 200% = both cores);
- throughput at batch size 8;
- memory: resident set after importing the runtime, after loading the model, and peak;
- start-up: importing the runtime, loading the model;
- agreement with PyTorch on 200 photos not used for calibration: same top class (all photos,
  and those PyTorch is at least 50% sure of), overlap of the top five, largest difference in
  any class probability.

Every run is stored with a **hardware fingerprint**: CPU model, the instruction sets that
matter for inference (AVX2, AVX-512, VNNI, AMX), usable CPUs, container quota, memory and
software versions. A daily job (05:07) runs the suite under the server's CPU lease.

ImageNet accuracy is quoted from timm's published results, not measured: the ImageNet
images cannot be redistributed. Agreement with PyTorch on licence-cleared photos is what
the lab measures instead.

## How it is built

```
image build ─► weights (GitHub releases, SHA-256)  ─┐
            ─► coco-cc bundle (release asset, SHA-256): 128 calibration, 200 agreement photos
            ─► export: PyTorch → ONNX in the PyTorch environment (torch.export, opset 18)
            ─► quantise: ONNX Runtime static QDQ, int8 weights per channel, uint8 activations
                 └─ check on the calibration photos the 32-bit model is ≥50% sure of; under 99%
                    agreement, find the layers that do the damage and keep the worst in 32-bit
            ─► models.json (files, sizes, hashes, tools, quantisation report)

run ─► child per variant: same preprocessing (timm's eval transform, checked to 1e-5)
    ─► measurements + probabilities ─► agreement ─► bench.run (PostgreSQL) ─► page
```

- **PyTorch environment** (`torch/`): CPU-only conda-forge builds installed from a lock file
  with every package's hash, into `/opt/torch`. The application never imports PyTorch; only
  the child processes use it (the PyTorch variant, and the export at build time).
- **Child processes** (`child.py`, `runner.py`): one JSON line in, one out; CPU-time cap, no
  file writes beyond PyTorch's probe of its private temporary directory, no secrets in the
  environment, killed with their process group at the deadline. ONNX Runtime children also
  get an address-space cap.
- **Sensitive layers** (`quantize.py`): each candidate layer is quantised on its own and the
  KL divergence of the output from the 32-bit probabilities measured; the most damaging are
  kept in 32-bit, 1, 2, 3, 4, 6, 8… at a time, until 99% of the calibration photos the 32-bit
  model is at least 50% sure of get its top class (near-tied answers on photos with no ImageNet
  class flip at any change, so they are reported but not used to judge). The report records
  the all-8-bit result, each step and the layers kept.
- **"Try it"** (`service.py`): an upload is decoded in its own process (JPEG, PNG or WebP;
  refused over 25 megapixels before decoding; EXIF orientation applied, metadata dropped;
  re-encoded at most 1024 pixels), then run through the three variants in two more
  processes, synchronously under the CPU lease. Nothing is stored.

## Commands

```bash
reluai-bench build --out /var/lib/reluai/data/bench   # image build (needs the PyTorch env)
reluai-bench build --photos ~/some-jpegs               # development, without the bundle
reluai-bench run [--model resnet18] [--threads 2] [--record]
reluai-bench classify photo.jpg --model mobilenetv3-small
```

Settings (`RELUAI_BENCH_*`): `DATA_DIR`, `TORCH_PYTHON`, `THREADS`, `ITERATIONS`, `WARMUP`,
child limits, "Try it" limits and the visitor quota (20 an hour).

## Tests

`tests/` runs the whole measuring path (children, agreement, API, quantisation) on a tiny
stand-in ONNX model, so CI needs neither the real models nor PyTorch.
`test_real_models.py` (marked slow) checks, when a built data directory and the PyTorch
environment are present, that the preprocessing matches timm's transform and that ONNX at
32 bits gives PyTorch's answers.

## Credits

MobileNetV3-Small: Howard et al. (2019). ResNet-18: He et al. (2016); weights from the
"ResNet strikes back" recipe (Wightman et al., 2021). Both via timm (Ross Wightman),
Apache 2.0, trained on ImageNet-1k. Photos: COCO 2017 validation set (Lin et al., 2014),
only photos whose Flickr licence allows reuse with changes; annotations CC BY 4.0.
