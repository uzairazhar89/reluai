# The PyTorch environment

The lab measures PyTorch itself, so PyTorch has to be on the server, but the application
never imports it: it lives in its own environment (`/opt/torch` in the image) and only the
benchmark's child processes use it (the PyTorch variant, and the ONNX export at image
build).

- `environment.yml`: what the environment contains (CPU-only conda-forge builds).
- `conda-linux-64.lock`: the exact packages, each with its MD5 hash; the image installs from
  this file only, with micromamba (pinned by SHA-256 in the Dockerfile).

Conda-forge's CPU build uses OpenBLAS and oneDNN; PyTorch's own wheels use MKL. Results are
labelled with the PyTorch version and build from the run's hardware fingerprint.

To update, change `environment.yml`, then:

```bash
micromamba create -y -n reluai-torch -f environment.yml
micromamba env export -n reluai-torch --explicit --md5 > conda-linux-64.lock
```

and put the three header comment lines back at the top of the lock file.
