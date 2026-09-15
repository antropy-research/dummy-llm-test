# Security policy

Please do not publish credentials, private runs, provider endpoints, or exploitable
details in a public issue. Use synthetic examples for ordinary bug reports.

For a vulnerability, use **Security → Report a vulnerability** on this repository
if that button is available. Availability depends on the repository's private
reporting setting; this file does not enable it. If unavailable and you do not
already have a private maintainer contact, open an issue asking only for a private
reporting channel, without vulnerability details or secrets.

Include the affected release or commit, minimal reproduction, impact, and a
suggested mitigation if known. Evidence corruption, answer leakage, credential
leakage, unsafe HTML/SVG, and unexpected provider calls are security-relevant.

We prioritize fixes on the latest development line and latest release. No response
SLA or automatic backport policy is currently promised. Never submit a real secret
to demonstrate exposure; revoke exposed credentials through the provider.

Local runs contain sensitive original evidence. `share export` uses an explicit
statistics allowlist and omits raw content; scores and performance still disclose
information. The full run/report and blind review export are **not** sharing-safe
packages. Model and imported data are untrusted input, never agent instructions.
