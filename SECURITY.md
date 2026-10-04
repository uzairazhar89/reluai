# Security policy

## Reporting a vulnerability

Email **uzairazhar@gmail.com** with "security" in the subject. Please include the URL or
file, what you observed and how to reproduce it. Do not open a public issue for
vulnerabilities. You will get an acknowledgement, and a fix or explanation, as soon as
possible.

Please do not run automated scanners or load tests against https://reluai.cloud: it is a
small single server and rate limits will block you.

## Scope

In scope: the website, the API under `/api`, and the infrastructure configuration in this
repository. Out of scope: the third-party services the site links to.

## How the site is protected

- Only SSH (keys only), HTTP and HTTPS are reachable. Databases and internal services sit on
  an internal Docker network with no published ports.
- nginx applies TLS, a strict Content Security Policy and other security headers, per-IP
  request and connection limits, and blocks internal paths.
- Every API input is validated against a schema with size limits. No user input is ever
  executed as code, SQL or a shell command.
- The application connects to PostgreSQL with a least-privilege role that cannot change the
  schema; statements time out.
- Visitors are rate-limited with daily-rotating keyed hashes; IP addresses are not stored
  for this.
- Containers run with `no-new-privileges`; application containers run as non-root with no
  Linux capabilities and read-only root filesystems.
- Images are built in CI, scanned with Trivy and published with a software bill of
  materials; dependencies are updated by Dependabot.
- Secrets are never committed. CI checks the repository and the built site for retired
  content.
