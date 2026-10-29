"use client";

import { useEffect, useRef, useState } from "react";

import { buttonClasses } from "@/components/button-link";
import { QueryProvider } from "@/components/query-provider";
import { Pill } from "@/components/status-badge";
import type {
  BenchModel,
  BenchRegistry,
  BenchSample,
  BenchTry,
  BenchVariant,
} from "@/lib/api/types";

import { ms, startup } from "./format";
import { benchErrorMessage } from "./messages";
import { MAX_PHOTO_BYTES, useRegistry, useSamples, useTry, type TryRequest } from "./queries";

type Choice = { kind: "sample"; sample: BenchSample } | { kind: "upload"; file: File; url: string };

function ModelPicker({
  models,
  value,
  onChange,
}: {
  models: BenchModel[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Model">
      <span className="text-xs text-faint">Model</span>
      {models.map((m) => (
        <button
          key={m.id}
          type="button"
          role="radio"
          aria-checked={value === m.id}
          onClick={() => onChange(m.id)}
          className={`rounded-sm px-2.5 py-1 text-sm ring-1 ring-inset transition-colors ${
            value === m.id
              ? "bg-surface-2 text-text ring-line-strong"
              : "text-muted ring-line hover:bg-surface-2/60 hover:text-text"
          }`}
        >
          {m.title}
          <span className="ml-1.5 text-xs text-faint">{m.params_millions} M</span>
        </button>
      ))}
    </div>
  );
}

function Prediction({ label, probability }: { label: string; probability: number }) {
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5">
      <span className="truncate text-sm text-text" title={label}>
        {label}
      </span>
      <span className="num text-right text-xs text-muted">{(probability * 100).toFixed(1)}%</span>
      <span className="col-span-2 h-1 overflow-hidden rounded-full bg-surface-2">
        <span
          className="block h-full rounded-full bg-muted"
          style={{ width: `${Math.max(1, probability * 100)}%` }}
        />
      </span>
    </li>
  );
}

function VariantCard({
  variant,
  result,
}: {
  variant: BenchVariant;
  result: BenchTry["results"][number];
}) {
  const reference = variant.id === "pytorch-fp32";
  return (
    <div className="space-y-3 rounded-md border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium text-text">{variant.title}</h4>
        {reference ? (
          <Pill>Reference</Pill>
        ) : result.same_top1_as_reference ? (
          <Pill tone="pass">Same answer</Pill>
        ) : (
          <Pill tone="warn">Different top class</Pill>
        )}
      </div>
      <p>
        <span className="num whitespace-nowrap text-2xl text-text">
          {ms(result.warm.inference).replace(" ms", "")}
          <span className="ml-1 text-sm text-muted">ms</span>
        </span>
        <span className="block text-xs text-muted">inference, median of 5 runs</span>
      </p>
      <ol aria-label={`${variant.title}: top 5`} className="space-y-2">
        {result.top5.map((p) => (
          <Prediction key={p.index} label={p.label} probability={p.probability} />
        ))}
      </ol>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-line/60 pt-3 text-xs">
        <dt className="text-muted">Preprocessing</dt>
        <dd className="num text-right text-text">{ms(result.warm.preprocess)}</dd>
        <dt className="text-muted">First call</dt>
        <dd className="num text-right text-text">{ms(result.first.inference)}</dd>
        <dt className="text-muted">Loading the model</dt>
        <dd className="num text-right text-text">{ms(result.load_ms)}</dd>
      </dl>
    </div>
  );
}

function Demo({
  models,
  variants,
  samples,
}: {
  models: BenchModel[];
  variants: BenchVariant[];
  samples: BenchSample[];
}) {
  const [model, setModel] = useState(models[0]?.id ?? "");
  const [choice, setChoice] = useState<Choice | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const run = useTry();
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadUrl = choice?.kind === "upload" ? choice.url : null;

  useEffect(
    () => () => {
      if (uploadUrl) URL.revokeObjectURL(uploadUrl);
    },
    [uploadUrl],
  );

  const start = (next: Choice, modelId = model) => {
    setLocalError(null);
    setChoice(next);
    const req: TryRequest =
      next.kind === "sample"
        ? { kind: "sample", name: next.sample.name, model: modelId }
        : { kind: "upload", file: next.file, model: modelId };
    run.mutate(req);
  };

  const onModel = (id: string) => {
    setModel(id);
    if (choice && !run.isPending) start(choice, id);
  };

  const onFile = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      setLocalError("Photos can be up to 5 MB.");
      return;
    }
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
      setLocalError("Choose a JPEG, PNG or WebP photo.");
      return;
    }
    start({ kind: "upload", file, url: URL.createObjectURL(file) });
  };

  const result = run.data && run.data.model === model ? run.data : undefined;
  const error = localError ?? (run.isError ? benchErrorMessage(run.error) : null);
  const preview = choice?.kind === "sample" ? choice.sample.url : choice?.url;

  return (
    <div className="space-y-5">
      <ModelPicker models={models} value={model} onChange={onModel} />

      <div className="space-y-2">
        <p className="text-xs text-faint">Pick a photo, or use your own</p>
        <ul className="grid grid-cols-4 gap-2 sm:grid-cols-8" aria-label="Sample photos">
          {samples.map((s, i) => {
            const active = choice?.kind === "sample" && choice.sample.name === s.name;
            return (
              <li key={s.name}>
                <button
                  type="button"
                  disabled={run.isPending}
                  onClick={() => start({ kind: "sample", sample: s })}
                  aria-label={`Classify sample photo ${i + 1}`}
                  aria-pressed={active}
                  className={`block aspect-square w-full overflow-hidden rounded-sm ring-2 ring-inset transition disabled:opacity-60 ${
                    active ? "ring-text" : "ring-transparent hover:ring-line-strong"
                  }`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element -- API image, fixed size */}
                  <img src={s.url} alt="" className="size-full object-cover" loading="lazy" />
                </button>
              </li>
            );
          })}
        </ul>
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            type="button"
            disabled={run.isPending}
            onClick={() => fileInput.current?.click()}
            className={buttonClasses("secondary", "sm")}
          >
            Upload your own photo
          </button>
          <span className="text-xs text-muted">
            JPEG, PNG or WebP up to 5 MB. Classified on the server and not stored.
          </span>
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            aria-label="Upload a photo to classify"
            onChange={(e) => {
              onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      <div aria-live="polite" className="min-h-6 text-sm">
        {run.isPending && (
          <p className="text-muted">
            Running on the server&apos;s CPU: starting PyTorch and ONNX Runtime in fresh processes,
            then classifying the photo with all three variants. This takes a few seconds.
          </p>
        )}
        {error && !run.isPending && <p className="text-fail">{error}</p>}
      </div>

      {preview && (result || run.isPending) && (
        <div className="grid gap-5 lg:grid-cols-[14rem_minmax(0,1fr)]">
          <figure className="max-w-xs space-y-2">
            {/* eslint-disable-next-line @next/next/no-img-element -- a sample or a local upload */}
            <img
              src={preview}
              alt={choice?.kind === "upload" ? "Your photo" : "The selected sample photo"}
              className="w-full rounded-sm border border-line object-cover"
            />
            {choice?.kind === "sample" && (
              <figcaption className="text-xs text-faint">
                Photo from COCO 2017 via{" "}
                <a href={choice.sample.source_url} className="prose-link">
                  Flickr
                </a>
                ,{" "}
                {choice.sample.licence_url ? (
                  <a href={choice.sample.licence_url} className="prose-link">
                    {choice.sample.licence}
                  </a>
                ) : (
                  choice.sample.licence
                )}
                .
              </figcaption>
            )}
          </figure>
          {result && (
            <div className="space-y-3">
              <div className="grid gap-3 md:grid-cols-3">
                {result.results.map((r) => {
                  const variant = variants.find((v) => v.id === r.variant);
                  return variant ? (
                    <VariantCard key={r.variant} variant={variant} result={r} />
                  ) : null;
                })}
              </div>
              <p className="text-xs text-muted">
                Each runtime started in a fresh process: PyTorch in{" "}
                {startup(result.import_ms.pytorch ?? 0)}, ONNX Runtime in{" "}
                {startup(result.import_ms.onnxruntime ?? 0)}. The whole request took{" "}
                {startup(result.total_ms)}
                {result.wait_ms > 100
                  ? ` after waiting ${startup(result.wait_ms)} for the CPU`
                  : ""}{" "}
                on hardware <span className="font-mono">{result.hardware_id}</span>.
                {result.source === "upload"
                  ? ` Your ${result.photo.format ?? "photo"} (${result.photo.width} × ${result.photo.height}) was decoded and re-encoded in an isolated process before classification.`
                  : ""}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Loader({
  initialRegistry,
  initialSamples,
}: {
  initialRegistry?: BenchRegistry;
  initialSamples?: BenchSample[];
}) {
  const registry = useRegistry(initialRegistry);
  const samples = useSamples(initialSamples);
  if (registry.data && samples.data) {
    return (
      <Demo
        models={registry.data.models}
        variants={registry.data.variants}
        samples={samples.data}
      />
    );
  }
  if (registry.isError || samples.isError) {
    return <p className="text-sm">{benchErrorMessage(registry.error ?? samples.error)}</p>;
  }
  return <p className="text-sm text-muted">Loading the models…</p>;
}

/** "Try it"; uses the registry and samples rendered with the page, or fetches them. */
export function TryDemo(props: {
  initialRegistry?: BenchRegistry;
  initialSamples?: BenchSample[];
}) {
  return (
    <QueryProvider>
      <Loader {...props} />
    </QueryProvider>
  );
}
