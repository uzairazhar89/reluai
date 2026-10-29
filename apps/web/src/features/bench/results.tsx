import { Pill } from "@/components/status-badge";
import type {
  BenchHardware,
  BenchModel,
  BenchRegistry,
  BenchResult,
  BenchRun,
} from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

import {
  agreementFor,
  agreementTone,
  flagLabel,
  hasInt8DotProduct,
  megabytes,
  memory,
  ms,
  percent,
  phases,
  resultsFor,
  speedup,
  startup,
  threadsLabel,
} from "./format";

function Hardware({ hw, run }: { hw: BenchHardware; run: BenchRun }) {
  const vnni = hasInt8DotProduct(hw.cpu.flags);
  return (
    <div className="rounded-md border border-line bg-surface p-5 text-sm">
      <p className="text-xs text-faint">Measured on this server</p>
      <p className="mt-1 text-base font-medium text-text">{hw.cpu.model}</p>
      <p className="mt-1 text-muted">
        {hw.usable_cpus} CPU{hw.usable_cpus === 1 ? "" : "s"} available to the benchmark
        {hw.cpu_quota ? ` (container quota ${hw.cpu_quota})` : ""}
        {hw.memory.total_mb ? `, ${memory(hw.memory.total_mb)} memory` : ""}
        {hw.cpu.hypervisor ? ", virtual machine" : ""}. {hw.os}.
      </p>
      <ul aria-label="Instruction sets" className="mt-3 flex flex-wrap gap-1.5">
        {hw.cpu.flags.map((f) => (
          <li key={f}>
            <Pill>{flagLabel(f)}</Pill>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-muted">
        {vnni
          ? "This CPU multiplies and adds 8-bit numbers in a single instruction (VNNI), which is what makes 8-bit models fast on x86."
          : "This CPU has no single instruction for 8-bit dot products (no VNNI), so 8-bit models gain less speed here than on newer CPUs."}
      </p>
      <p className="mt-3 text-xs text-faint">
        Run {formatDateTime(run.ran_at)} ({run.label === "scheduled" ? "daily run" : "manual run"},{" "}
        {Math.round(run.duration_seconds)} s). Hardware id{" "}
        <span className="font-mono">{hw.id}</span>.{" "}
        {Object.entries(hw.versions)
          .map(([k, v]) => `${k} ${v}`)
          .join(" · ")}
        .
      </p>
    </div>
  );
}

/** A percentage with a decimal only when it has one: 100%, 90.5%. */
function share(value: number) {
  return percent(value, value % 1 ? 1 : 0);
}

function variantTitle(registry: BenchRegistry, id: string) {
  return registry.variants.find((v) => v.id === id)?.title ?? id;
}

/** Median latency of one photo, split into its phases: the memorable picture of the lab. */
function PhaseBars({
  registry,
  results,
  photos,
}: {
  registry: BenchRegistry;
  results: BenchResult[];
  photos: number;
}) {
  const longest = Math.max(...results.map((r) => phases(r.latency_ms).sum));
  return (
    <figure className="space-y-2.5">
      {results.map((r) => {
        const p = phases(r.latency_ms);
        const w = (v: number) => `${(100 * v) / longest}%`;
        return (
          <div key={`${r.variant}-${r.threads}`} className="grid gap-1 sm:grid-cols-[13rem_1fr]">
            <span className="text-sm text-text">
              {variantTitle(registry, r.variant)}
              <span className="text-muted"> · {threadsLabel(r.threads)}</span>
            </span>
            <span className="flex items-center gap-3">
              <span className="flex h-3 min-w-0 flex-1 overflow-hidden rounded-sm bg-surface-2">
                <span className="h-full bg-line-strong" style={{ width: w(p.pre) }} />
                <span className="h-full bg-text" style={{ width: w(p.inf) }} />
                <span className="h-full bg-faint" style={{ width: w(p.post) }} />
              </span>
              <span className="num w-36 shrink-0 text-right text-sm text-muted">
                <span className="text-text">{ms(p.inf)}</span> of {ms(p.sum)}
              </span>
            </span>
          </div>
        );
      })}
      <figcaption className="flex flex-wrap gap-x-5 gap-y-1 pt-1 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-sm bg-line-strong" /> Preprocessing (decode,
          resize, normalise)
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-sm bg-text" /> Inference
        </span>
        <span className="flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-sm bg-faint" /> Softmax and top 5
        </span>
        <span>
          Figures: inference of the whole photo. Medians of {results[0]?.iterations ?? 0} runs over{" "}
          {photos} photos, one at a time.
        </span>
      </figcaption>
    </figure>
  );
}

function Table({
  registry,
  run,
  model,
}: {
  registry: BenchRegistry;
  run: BenchRun;
  model: BenchModel;
}) {
  const rows = resultsFor(run.results, model.id);
  return (
    <div
      className="overflow-x-auto"
      tabIndex={0}
      role="group"
      aria-label={`${model.title} measurements`}
    >
      <table className="w-full min-w-[900px] whitespace-nowrap text-sm">
        <caption className="sr-only">{model.title}: measurements per variant</caption>
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            {[
              ["Variant", "left"],
              ["Inference p50", "right"],
              ["p95", "right"],
              ["Whole photo p50", "right"],
              ["Batch of 8", "right"],
              ["CPU", "right"],
              ["Peak memory", "right"],
              ["File", "right"],
              ["Same top class", "right"],
              ["When PyTorch is sure", "right"],
            ].map(([h, align]) => (
              <th
                key={h}
                scope="col"
                className={`py-2 pr-3 font-medium ${align === "left" ? "text-left" : "text-right"}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const agree = agreementFor(run.agreement, r.model, r.variant);
            return (
              <tr key={`${r.variant}-${r.threads}`} className="border-b border-line/60">
                <th scope="row" className="py-2 pr-3 text-left font-medium text-text">
                  {variantTitle(registry, r.variant)}
                  <span className="block text-xs font-normal text-muted">
                    {threadsLabel(r.threads)}
                  </span>
                </th>
                <td className="num py-2 pr-3 text-right text-text">
                  {ms(r.latency_ms.inference.p50)}
                </td>
                <td className="num py-2 pr-3 text-right">{ms(r.latency_ms.inference.p95)}</td>
                <td className="num py-2 pr-3 text-right">{ms(r.latency_ms.total.p50)}</td>
                <td className="num py-2 pr-3 text-right">
                  {Math.round(r.throughput.images_per_second).toLocaleString("en-GB")} /s
                </td>
                <td className="num py-2 pr-3 text-right">{percent(r.cpu_percent)}</td>
                <td className="num py-2 pr-3 text-right">{memory(r.memory_mb.peak)}</td>
                <td className="num py-2 pr-3 text-right">{megabytes(r.size_bytes)}</td>
                {r.variant === "pytorch-fp32" ? (
                  <td colSpan={2} className="py-2 text-right text-faint">
                    reference
                  </td>
                ) : agree ? (
                  <>
                    <td className="num py-2 pr-3 text-right">{share(agree.top1_agreement)}</td>
                    <td className="num py-2 text-right">
                      <Pill tone={agreementTone(agree.top1_agreement_confident)}>
                        {share(agree.top1_agreement_confident)}
                      </Pill>
                    </td>
                  </>
                ) : (
                  <td colSpan={2} className="py-2 text-right">
                    –
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** "3.1× faster than", "1.1× slower than" or "about as fast as", the ratio in bold. */
function Compared({ reference, value }: { reference: number; value: number }) {
  const phrase = speedup(reference, value);
  if (phrase === "about the same") return <>about as fast as</>;
  return (
    <>
      <strong>{phrase}</strong> than
    </>
  );
}

/** One sentence per comparison, computed from the run: what a reader should take away. */
function Findings({ run, model }: { run: BenchRun; model: BenchModel }) {
  const top = Math.max(...resultsFor(run.results, model.id).map((r) => r.threads));
  const at = (variant: string) =>
    run.results.find((r) => r.model === model.id && r.variant === variant && r.threads === top);
  const torch = at("pytorch-fp32");
  const fp32 = at("onnx-fp32");
  const int8 = at("onnx-int8");
  if (!torch || !fp32 || !int8) return null;
  const agree = agreementFor(run.agreement, model.id, "onnx-int8");
  const fp32Agree = agreementFor(run.agreement, model.id, "onnx-fp32");
  const pre = phases(fp32.latency_ms);
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      <li>
        Exported to ONNX, the same 32-bit model ran{" "}
        <Compared
          reference={torch.latency_ms.inference.p50}
          value={fp32.latency_ms.inference.p50}
        />{" "}
        PyTorch ({threadsLabel(top)}) and used {memory(torch.memory_mb.peak - fp32.memory_mb.peak)}{" "}
        less memory
        {fp32Agree
          ? `; its answers matched PyTorch's on all ${fp32Agree.photos} photos to within ${fp32Agree.max_probability_difference.toExponential(0)} in probability`
          : ""}
        .
      </li>
      <li>
        In 8 bits it ran{" "}
        <Compared reference={fp32.latency_ms.inference.p50} value={int8.latency_ms.inference.p50} />{" "}
        ONNX at 32 bits and was {(fp32.size_bytes / int8.size_bytes).toFixed(1)}× smaller
        {agree
          ? `. It picked PyTorch's top class for ${share(agree.top1_agreement)} of ${agree.photos} photos, and for ${agree.top1_agreement_confident === 100 ? "all" : share(agree.top1_agreement_confident) + " of the"} ${agree.confident_photos} where PyTorch was at least 50% sure${agree.top1_agreement_confident === 100 && agree.top1_agreement < 100 ? ": every difference was on a photo PyTorch was unsure about, where the top two answers are close" : ""}`
          : ""}
        .
      </li>
      <li>
        For a photo end to end, preprocessing took {ms(pre.pre)} against {ms(pre.inf)} of inference
        with ONNX at 32 bits
        {pre.pre > pre.inf
          ? ": for a model this size, decoding and resizing the image costs more than the network."
          : "."}
      </li>
      <li>
        Starting PyTorch in a fresh process took {startup(torch.import_ms)}, ONNX Runtime{" "}
        {startup(fp32.import_ms)}: a cost paid once per process, not per photo.
      </li>
    </ul>
  );
}

function Quantisation({ model }: { model: BenchModel }) {
  const q = model.quantisation;
  const kept = q.kept_fp32.length;
  const steps = q.steps ?? [];
  return (
    <div className="space-y-2 text-sm">
      <p>
        <strong>8-bit conversion.</strong> With every layer in 8 bits, the model picked the 32-bit
        model&apos;s top class on {share(q.all_layers.agreement)} of the {q.calibration_photos}{" "}
        calibration photos, and on {share(q.all_layers.confident_agreement)} of the{" "}
        {q.confident_photos} it was at least 50% sure of.{" "}
        {kept === 0
          ? `That meets the ${share(q.target_agreement)} target on the sure photos, so every layer runs in 8 bits.`
          : `Measuring each layer alone found the ${kept} (of ${q.candidates ?? "?"}) that hurt most; with those left in 32-bit it agreed on ${share(q.final.confident_agreement)} of the sure photos (${share(q.final.agreement)} of all)${q.final.confident_agreement < q.target_agreement ? `, short of the ${share(q.target_agreement)} target` : ""}.`}
      </p>
      {steps.length > 0 && (
        <p className="text-xs text-muted">
          Agreement on the sure photos with the most damaging layers kept in 32-bit:{" "}
          {steps.map((st) => `${st.kept_fp32} → ${share(st.confident_agreement)}`).join(", ")}. Not
          a smooth curve: layers interact, which is why each step is measured rather than predicted.
        </p>
      )}
      {kept > 0 && (
        <details>
          <summary className="cursor-pointer text-text hover:underline">
            The {kept} layer{kept === 1 ? "" : "s"} kept in 32-bit
          </summary>
          <ol className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            {q.kept_fp32.map((k) => (
              <li key={k.node} className="flex justify-between gap-3 border-b border-line/50 py-1">
                <span className="font-mono text-muted">{k.op}</span>
                <span className="num">damage alone: KL {k.kl_when_alone.toFixed(3)}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

export function BenchResults({ run, registry }: { run: BenchRun; registry: BenchRegistry }) {
  return (
    <div className="space-y-10">
      <Hardware hw={run.hardware} run={run} />
      {registry.models.map((model) => {
        const rows = resultsFor(run.results, model.id);
        if (rows.length === 0) return null;
        return (
          <div key={model.id} className="space-y-4">
            <h3 className="heading text-base text-text">
              {model.title}
              <span className="ml-2 text-sm font-normal text-muted">
                {model.params_millions} M parameters · ImageNet top-1{" "}
                {model.published_top1.toFixed(1)}% as published by timm
              </span>
            </h3>
            <PhaseBars
              registry={registry}
              results={rows}
              photos={Number(run.protocol.latency_photos ?? 0)}
            />
            <Table registry={registry} run={run} model={model} />
            <Findings run={run} model={model} />
            <Quantisation model={model} />
          </div>
        );
      })}
      <p className="text-sm text-faint">
        “Same top class” is measured on {run.protocol.agreement_photos as number} photos that were
        not used for calibration; “when PyTorch is sure” counts only those where its top class has
        at least 50% probability. Many of the photos show nothing in ImageNet&apos;s 1,000 classes,
        and there the top answer is a near-tie that any change can flip. ImageNet accuracy is quoted
        from{" "}
        <a href={registry.published_accuracy_source} className="prose-link">
          timm&apos;s published results
        </a>{" "}
        and not measured here: the ImageNet images cannot be redistributed. Latency percentiles come
        from {run.results[0]?.iterations ?? 0} photos per variant after{" "}
        {run.results[0]?.warmup ?? 0} warm-up runs; the 95th percentile includes interference from
        the server&apos;s other work.
      </p>
    </div>
  );
}
