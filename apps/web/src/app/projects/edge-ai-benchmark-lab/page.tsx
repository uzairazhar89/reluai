import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink } from "@/components/button-link";
import { JsonLd } from "@/components/json-ld";
import { ProjectSection, ProjectToc } from "@/components/project-page";
import { Pill } from "@/components/status-badge";
import { projects } from "@/content/projects";
import { BenchArchitecture } from "@/features/bench/architecture";
import { BenchResults } from "@/features/bench/results";
import { TryDemo } from "@/features/bench/try-demo";
import { serverGet } from "@/lib/api/server";
import type { BenchRegistry, BenchRun, BenchSample } from "@/lib/api/types";
import { site } from "@/lib/site";

export const revalidate = 60;

const project = projects.find((p) => p.slug === "edge-ai-benchmark-lab")!;
const repoTree = `${site.repo}/tree/main/${project.repoPath}`;
const repoFile = (path: string) =>
  `${site.repo}/blob/main/${project.repoPath}/src/reluai_bench/${path}`;

export const metadata: Metadata = {
  title: project.title,
  description:
    "Image classifiers run as PyTorch, ONNX Runtime and 8-bit ONNX on this server's CPU: " +
    "latency per phase, throughput, memory, size and agreement with PyTorch, measured daily " +
    "in isolated processes and recorded with the hardware. Try it with your own photo.",
  alternates: { canonical: `/projects/${project.slug}` },
};

const stack = [
  ["Models", "MobileNetV3-Small and ResNet-18 (timm, ImageNet-1k), weights pinned by SHA-256"],
  ["Variants", "PyTorch FP32 (eager) · ONNX Runtime FP32 · ONNX Runtime INT8 (static, QDQ)"],
  ["PyTorch", "2.14 CPU build from conda-forge in its own environment, exact packages locked"],
  ["Export", "torch.onnx.export with torch.export graph capture, dynamic batch, opset 18"],
  ["Quantisation", "ONNX Runtime static quantisation: weights per channel, activations per tensor"],
  ["Calibration", "128 COCO 2017 photos under reuse licences; 200 others for agreement"],
  ["Runner", "A fresh child process per measurement, with CPU, memory and time limits"],
  ["Interface", "FastAPI, a daily Procrastinate job, Next.js; results stored in PostgreSQL"],
] as const;

const failures = [
  [
    "8-bit conversion ruins a model",
    "Every 8-bit model is checked against the 32-bit one on the calibration photos when it is built. If it gives a different top class on photos the 32-bit model is sure of, each layer is quantised on its own to find the ones that do the damage, and the worst are kept in 32-bit until 99% agree. The report shows the all-8-bit result, every step of the search and the layers kept.",
  ],
  [
    "An uploaded file is not what it claims",
    "It is decoded in its own process with no secrets, a CPU cap and no file writes. Only JPEG, PNG and WebP are accepted, images over 25 megapixels are refused before their pixels are decoded, EXIF orientation is applied and all metadata dropped, and the models only ever see the clean re-encoded copy.",
  ],
  [
    "A measurement hangs or crashes",
    "Each child process has a wall-clock deadline and is killed with its process group when it passes; the API answers with a plain message. A crashed child takes nothing else down.",
  ],
  [
    "One variant colours another's numbers",
    "Every model, variant and thread count runs in a new process: no shared memory, thread pools or caches, so peak memory and start-up are each variant's own.",
  ],
  [
    "A different CPU gives different numbers",
    "Every run records the CPU model and the instruction sets that matter for inference (AVX2, AVX-512, VNNI, AMX), the CPUs available, the container quota and the software versions. Runs are only comparable on the same hardware id.",
  ],
  [
    "The server is busy",
    "Benchmarks and “Try it” take the server's single CPU lease; a visitor waits at most 20 seconds and is then asked to try again. Each visitor gets 20 runs an hour.",
  ],
  [
    "PyTorch is missing or broken",
    "The ONNX variants keep working and the API says which part is unavailable; the image build fails instead of shipping a lab with a variant silently missing.",
  ],
] as const;

export default async function EdgeBenchmarkPage() {
  const [registry, latest, samples] = await Promise.all([
    serverGet<BenchRegistry>("/api/bench/registry", revalidate),
    serverGet<BenchRun | null>("/api/bench/runs/latest", revalidate),
    serverGet<BenchSample[]>("/api/bench/samples", revalidate),
  ]);

  return (
    <>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "SoftwareSourceCode",
          name: project.title,
          description: metadata.description,
          codeRepository: repoTree,
          programmingLanguage: ["Python", "TypeScript"],
          author: { "@type": "Person", name: site.name, url: site.url },
          license: "https://opensource.org/licenses/MIT",
        }}
      />

      <header className="mx-auto max-w-6xl px-5 pb-12 pt-12 sm:px-8 md:pt-16">
        <nav aria-label="Breadcrumb" className="text-sm text-muted">
          <Link href="/projects" className="hover:text-text">
            Projects
          </Link>
          <span aria-hidden className="mx-2 text-faint">
            /
          </span>
          <span aria-current="page">{project.title}</span>
        </nav>
        <h1 className="display mt-5 max-w-[22ch] text-[2.1rem] leading-[1.06] sm:text-[2.6rem]">
          {project.title}
        </h1>
        <p className="mt-5 max-w-[62ch] text-lg text-muted">
          The same image classifier three ways: as trained in PyTorch, exported to ONNX, and
          quantised to 8 bits. Each runs on this server&apos;s CPU in its own process, and the lab
          measures what changes: speed, memory, file size, and whether the answers stay the same.
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Pill tone="pass">Live</Pill>
          <Pill>Computer vision</Pill>
          <Pill>Measured daily on this server</Pill>
          <Pill>Licence-cleared photos</Pill>
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <ButtonLink href="#demo">Try it with a photo</ButtonLink>
          <ButtonLink href={repoTree} variant="secondary" external>
            Source code
          </ButtonLink>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-12 px-5 pb-24 sm:px-8 lg:grid-cols-[12rem_minmax(0,1fr)]">
        <ProjectToc />
        <div className="min-w-0 space-y-14">
          <ProjectSection id="problem">
            <p>
              A model that works in a notebook still has to run somewhere: a CPU server, a camera, a
              phone. Teams reach for ONNX and 8-bit quantisation because they are &ldquo;faster and
              smaller&rdquo;, then find the speed-up depends on the model and the processor, and
              that an 8-bit model can quietly give different answers.
            </p>
            <p>
              Published benchmarks rarely help: they come from someone else&apos;s hardware, time
              only the network and not the image decoding around it, and seldom say whether the
              faster model still agrees with the original.
            </p>
          </ProjectSection>

          <ProjectSection id="why">
            <p>
              Choosing where and how a model runs is a cost and reliability decision. The useful
              numbers are the ones from the machine you will deploy on, for the whole request
              (decode, resize, infer), with the memory each option needs and evidence that its
              answers did not change. That is what this lab produces, every day, for the server this
              site runs on. It also picks the models for the Street Scene project on the same
              evidence.
            </p>
          </ProjectSection>

          <ProjectSection id="solution">
            <p>
              Two ImageNet classifiers with very different designs, MobileNetV3-Small (built for
              phones) and ResNet-18 (plain convolutions), are prepared three ways when the server
              image is built: the PyTorch model as trained, its ONNX export, and an 8-bit version
              calibrated on real photos. A daily job runs every variant in a fresh, isolated process
              on the same photos and records latency per phase, throughput, CPU use, memory, file
              size and how often each variant picks PyTorch&apos;s top class.
            </p>
            <p>
              <strong>Why ONNX?</strong> PyTorch runs a model op by op as Python asks for it. An
              ONNX file is the whole graph, so a runtime can fuse operations (a convolution and its
              batch normalisation become one), plan memory once, and pick kernels for the CPU it
              finds. The weights and the answers stay the same.
            </p>
            <p>
              <strong>Why 8 bits?</strong> Storing weights as 8-bit integers makes the file four
              times smaller, and CPUs with VNNI or AMX instructions multiply 8-bit numbers several
              times faster than 32-bit ones. The cost is precision: each tensor gets 256 levels,
              chosen from the ranges seen on calibration photos, and a layer whose values span a
              huge range loses the detail in the small ones.
            </p>
            <p>
              <strong>When is a CPU enough?</strong> When a photo takes milliseconds and requests
              arrive one at a time, as here: a GPU would sit idle. Edge hardware changes the
              picture: NPUs and phone accelerators often run only 8-bit models, so the quantisation
              step stops being optional, and its accuracy check matters more.
            </p>
          </ProjectSection>

          <ProjectSection id="architecture">
            <BenchArchitecture />
          </ProjectSection>

          <ProjectSection id="implementation">
            <dl className="divide-y divide-line/60">
              {stack.map(([term, desc]) => (
                <div key={term} className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr] sm:gap-6">
                  <dt className="font-medium text-text">{term}</dt>
                  <dd>{desc}</dd>
                </div>
              ))}
            </dl>
            <p>
              <strong>One input for every variant.</strong> Preprocessing is a single function
              (shorter side to 256 pixels with bicubic resampling, centre crop, normalise), checked
              against timm&apos;s own evaluation transform to within 0.00001. It runs inside each
              variant&apos;s process and is timed separately, so the &ldquo;whole photo&rdquo;
              figure is what a real request costs.
            </p>
            <p>
              <strong>What is measured.</strong> After warm-up runs, each process classifies the
              same photos one at a time and times preprocessing, inference and postprocessing
              separately; the median and 95th percentile are reported. CPU use is CPU time over wall
              time (200% means both cores busy). Throughput uses batches of eight. Memory is read
              from the process itself after importing the runtime, after loading the model, and at
              its peak. Start-up (importing the runtime, loading the model) is reported apart,
              because a server pays it once and a command-line tool every time.
            </p>
            <p>
              <strong>Agreement, not just speed.</strong> At the highest thread count every variant
              also classifies 200 photos that were not used for calibration, and its probabilities
              are compared with PyTorch&apos;s: the share with the same top class (on every photo,
              and on those where PyTorch is at least 50% sure), the overlap of the top five, and the
              largest probability difference. ONNX at 32 bits should match to about one part in a
              million; 8 bits will not, and the question is by how much.
            </p>
            <p>
              <strong>Finding the layers that cannot be 8-bit.</strong> Quantised in every layer,
              MobileNetV3 gave a different top class from the 32-bit model on every one of the 128
              calibration photos. Right after its first layer, one channel reaches about 56 while
              ten of the sixteen stay below 1; one 8-bit range for the whole tensor has steps of
              about 0.2, so those ten keep only a few distinct values, and the error compounds from
              there. So at build time each layer is quantised on its own and the damage measured (KL
              divergence from the 32-bit probabilities), and the most damaging are kept in 32-bit, a
              few at a time, until the 8-bit model gives the 32-bit model&apos;s answer on at least
              99% of the calibration photos the 32-bit model is at least 50% sure of. Photos showing
              nothing in ImageNet&apos;s classes get near-tied answers that any change flips, so
              they are reported but not used to judge. The published agreement is measured on
              different photos.
            </p>
          </ProjectSection>

          <ProjectSection id="demo">
            <p>
              Pick a photo or upload your own: it is classified now, on this server, by the three
              variants of the model you choose, each in a fresh process. You see each variant&apos;s
              top five classes, how long inference took and whether it agrees with PyTorch.
            </p>
            <div className="pt-2 text-base">
              <TryDemo
                initialRegistry={registry.ok ? registry.data : undefined}
                initialSamples={samples.ok ? samples.data : undefined}
              />
            </div>
            <p className="text-sm text-faint">
              Portfolio demonstration. Each visitor can run 20 photos an hour. Uploaded photos are
              decoded, classified and discarded; nothing is stored. The models know the 1,000
              ImageNet classes only, so most photos of people or scenes get a guess about an object
              in them.
            </p>
          </ProjectSection>

          <ProjectSection id="results">
            {registry.ok && latest.ok && latest.data ? (
              <BenchResults run={latest.data} registry={registry.data} />
            ) : (
              <p>
                Results are read from the running system and are not available right now. They
                appear after the first daily run of the benchmark on this server.
              </p>
            )}
          </ProjectSection>

          <ProjectSection id="failure-handling">
            <dl className="divide-y divide-line/60">
              {failures.map(([term, desc]) => (
                <div key={term} className="py-3.5">
                  <dt className="font-medium text-text">{term}</dt>
                  <dd className="mt-1">{desc}</dd>
                </div>
              ))}
            </dl>
          </ProjectSection>

          <ProjectSection id="deployment">
            <p>
              Everything heavy happens when the server image is built: the weights and photos are
              downloaded from pinned sources and checked against their SHA-256 hashes, each model is
              exported in the PyTorch environment, and the 8-bit versions are calibrated, checked
              and written with the same ONNX Runtime that serves them. The server only loads files.
            </p>
            <p>
              PyTorch comes from conda-forge&apos;s CPU builds, installed from a lock file that
              lists every package with its hash, into its own directory. The application&apos;s
              Python never imports it; only the benchmark&apos;s child processes do. A daily job
              runs the suite (about two minutes of CPU) under the server&apos;s CPU lease, so the
              results above always come from this machine.
            </p>
          </ProjectSection>

          <ProjectSection id="cost">
            <p>
              <strong>$0.</strong> No API calls and no GPU: models, photos and runtimes are open
              source or openly licensed, and everything runs on the same 2-vCPU server as the rest
              of the site. The daily run costs about two minutes of CPU; the PyTorch environment
              adds about 1 GB to the server image.
            </p>
          </ProjectSection>

          <ProjectSection id="limitations">
            <ul className="list-disc space-y-1.5 pl-5">
              <li>
                One CPU, shared: the server also runs the site, so the 95th percentile includes
                other work, and absolute numbers only hold for this hardware id.
              </li>
              <li>
                ImageNet accuracy is not measured here (its images cannot be redistributed);
                agreement with PyTorch on other photos stands in for &ldquo;did quantisation
                hurt&rdquo;, and published accuracy is quoted from timm.
              </li>
              <li>
                Two classification models. Detection, pose and face and number-plate models for
                Street Scene Intelligence are the next part of the lab.
              </li>
              <li>
                PyTorch runs in eager mode, as most code does; torch.compile, OpenVINO and other
                runtimes are not compared.
              </li>
              <li>
                The 8-bit conversion keeps whole layers in 32-bit; finer fixes (per-channel
                activation scales, cross-layer equalisation, quantisation-aware training) would
                recover more speed and are not attempted.
              </li>
            </ul>
          </ProjectSection>

          <ProjectSection id="source">
            <p>The full source is on GitHub under the MIT licence, with the tests.</p>
            <ul className="space-y-2">
              {(
                [
                  ["registry.py", "The models, their pinned weights and the three variants"],
                  ["preprocess.py", "The one preprocessing function, and upload sanitising"],
                  ["export_torch.py", "PyTorch to ONNX, in the PyTorch environment"],
                  ["quantize.py", "8-bit conversion and the search for sensitive layers"],
                  ["child.py", "The isolated process that loads a variant and measures it"],
                  ["benchmark.py", "The suite, and agreement with PyTorch"],
                  ["hardware.py", "The hardware fingerprint"],
                  ["service.py", "Stored runs and “Try it”"],
                ] as const
              ).map(([file, what]) => (
                <li key={file} className="flex flex-wrap gap-x-3">
                  <a href={repoFile(file)} className="prose-link font-mono text-sm">
                    {file}
                  </a>
                  <span>{what}</span>
                </li>
              ))}
            </ul>
            <div className="pt-2">
              <ButtonLink href={repoTree} variant="secondary" external>
                View on GitHub
              </ButtonLink>
            </div>
            <p className="text-sm text-faint">
              Models: MobileNetV3-Small (Howard et al., 2019) and ResNet-18 (He et al., 2016) with
              weights from the timm library by Ross Wightman, Apache 2.0, trained on ImageNet-1k.
              Photos: COCO 2017 validation set (Lin et al., 2014), only photos whose Flickr licence
              allows reuse; annotations CC BY 4.0. Details on the{" "}
              <Link href="/data" className="prose-link">
                data page
              </Link>
              .
            </p>
          </ProjectSection>
        </div>
      </div>
    </>
  );
}
