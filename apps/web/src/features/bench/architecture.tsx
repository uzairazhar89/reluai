/**
 * The Benchmark Lab as an HTML flow: what happens once, when the server image is built, and
 * what happens every time the benchmark runs (daily, or a visitor's "Try it").
 */
const build = [
  ["Pinned weights", "timm ImageNet classifiers from GitHub releases, checked by SHA-256"],
  ["Export", "PyTorch → ONNX in a separate PyTorch environment (torch.export graph capture)"],
  ["Calibrate", "128 licence-cleared COCO photos run through the 32-bit graph"],
  ["Quantise", "Weights and activations to 8 bits; layers that wreck the answers stay 32-bit"],
];

const run = [
  ["Fresh process", "One per model, variant and thread count: no shared caches or memory"],
  ["Same input", "One preprocessing function feeds every variant (timm's evaluation transform)"],
  ["Measure", "Latency per phase, throughput, CPU, memory, start-up; answers per photo"],
  ["Record", "Stored with the CPU model, its instruction sets and the software versions"],
];

function Steps({ title, steps, accent }: { title: string; steps: string[][]; accent?: boolean }) {
  return (
    <div>
      <p className="mb-2 text-xs font-medium text-faint">{title}</p>
      <ol className="space-y-1.5">
        {steps.map(([name, note], i) => (
          <li
            key={name}
            className={`flex gap-3 rounded-sm px-3 py-2 ${
              accent ? "ring-1 ring-inset ring-line-strong" : "bg-surface-2"
            }`}
          >
            <span className="num w-4 shrink-0 text-xs text-faint">{i + 1}</span>
            <span>
              <span className="block font-medium text-text">{name}</span>
              <span className="block text-xs text-muted">{note}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function BenchArchitecture() {
  return (
    <figure className="rounded-md border border-line bg-surface p-5 text-sm">
      <div className="grid gap-4 md:grid-cols-2">
        <Steps title="Once, when the server image is built" steps={build} />
        <Steps title="Every run (daily, and each “Try it”)" steps={run} accent />
      </div>
      <p className="mt-4 text-xs text-muted">
        <span className="font-medium text-text">Isolation.</span> PyTorch lives in its own
        environment that the application never imports; ONNX Runtime runs under the
        application&apos;s Python. Either way each measurement is a child process with a CPU-time
        cap, no secrets, no file writes, and a deadline. An uploaded photo is decoded and re-encoded
        in its own capped process before any model sees it.
      </p>
      <figcaption className="sr-only">
        At build time the model weights are downloaded and checked, exported from PyTorch to ONNX,
        calibrated on licence-cleared photos and quantised to 8 bits, keeping sensitive layers in
        32-bit. At run time every variant runs in its own isolated process on the same inputs, and
        its latency, throughput, memory and answers are recorded with the hardware fingerprint.
      </figcaption>
    </figure>
  );
}
