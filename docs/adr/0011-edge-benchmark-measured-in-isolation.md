# 0011. Model variants are measured on the serving machine, each in its own process, with agreement as the accuracy check

Date: 2026-10-27. Status: accepted.

## Context

The Edge AI Benchmark Lab (P3) compares a model as trained in PyTorch with its ONNX export
and an 8-bit quantised version, and picks models for Street Scene Intelligence (P6).
Benchmarks are easy to make misleading:

- numbers from other hardware, or with the image decoding left out, do not describe the
  machine and request that matter;
- runtimes in one process share thread pools, caches and memory, so the second variant
  measured inherits the first one's state;
- a quantised model can be fast and wrong, and ImageNet's images (the usual accuracy test)
  cannot be redistributed;
- PyTorch is large, and the site runs on a 2-vCPU, 8 GB server with a $0 budget.

## Decision

1. **Measure where it runs, and say on what.** The suite runs daily on the server itself
   under the CPU lease, and every run stores a hardware fingerprint (CPU model, inference
   instruction sets, usable CPUs, quota, memory, versions). Numbers are only compared
   within one hardware id.
2. **One process per measurement.** Each model × variant × thread count runs in a fresh
   child process with a CPU-time cap, no secrets and a deadline. Latency is split into
   preprocessing, inference and postprocessing; start-up is reported separately.
3. **Same input everywhere.** One preprocessing function (timm's evaluation transform,
   checked to 1e-5) feeds every variant.
4. **Agreement instead of ImageNet accuracy.** Each variant classifies 200 licence-cleared
   COCO photos not used for calibration; the share with PyTorch's top class (on all photos,
   and on those PyTorch is at least 50% sure of), top-5 overlap and the largest probability
   difference are published. Many COCO photos show nothing in ImageNet's classes; their top
   answers are near-ties, so agreement on them says little about damage. ImageNet accuracy
   is quoted from timm and labelled as published.
5. **Quantisation is checked when it is built.** If the all-8-bit model agrees with the
   32-bit one on fewer than 99% of the calibration photos the 32-bit model is sure of, layers
   are quantised one at a time to measure their damage, and the worst are kept in 32-bit until
   the target is met. The report (all-8-bit result, each step, layers kept) is published.
6. **PyTorch in its own environment.** CPU-only conda-forge builds, installed from a lock
   file with every package's hash, in `/opt/torch`. Only child processes use it; the
   application never imports it.
7. **Data through a pinned release.** The calibration and agreement photos come from a
   bundle published by the `assets` workflow (COCO photos whose licence allows reuse with
   changes) and are pinned by SHA-256, like the model weights.

## Consequences

- Results describe this server, not CPUs in general; the page says which CPU and why it
  matters (VNNI for 8-bit).
- The 95th percentile includes the server's other work. Medians are stable; tails are
  honest about a shared machine.
- The image grows by about 1 GB (the PyTorch environment) and the API's memory limit rises
  to 1.5 GB, because a "Try it" PyTorch child needs about 0.5 GB.
- Keeping whole layers in 32-bit restores agreement but gives back some speed; finer
  methods (per-channel activation scales, cross-layer equalisation, quantisation-aware
  training) are possible later and can be judged on the same measurements.
- The same harness can measure P6's candidate detectors, pose, face and plate models.
