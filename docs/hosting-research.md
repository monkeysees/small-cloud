# Hosting feasibility research

Research date: 2026-09-07. Scope: [issue #2](https://github.com/monkeysees/small-cloud/issues/2), [specification](spec.md), and ADRs 0001, 0003, 0007, and 0008. This is a documented feasibility assessment, not deployment evidence. No cloud resources were created during the assessment.

## Approved implementation direction — 2026-09-08

The operator selected Hetzner and authorized infrastructure setup in [#17](https://github.com/monkeysees/small-cloud/issues/17). This supersedes the selection hold in the historical assessment below; isolation, residency, capacity and cost acceptance remain unproven. Use the operator's `small-cloud` project in Germany and `small-cloud.monkeysees.one`, with DNS managed in the existing Cloudflare zone.

For each build, create a fresh x86 VM, preferring CX23 across the German locations (`nbg1`, `fsn1`) before falling back to CPX22 across those locations. Both sizes provide 2 vCPUs and 4 GiB RAM. Do not fall back outside Germany or to another architecture. Start without a prewarmed pool or shared build cache. A prepared, secret-free builder image may reduce bootstrap work, but does not reserve provider capacity.

Use bounded provisioning retries with clear capacity-failure feedback. Reconcile ambiguous create outcomes before retrying so a timeout cannot silently create duplicate builders. Each VM executes only one build; delete it and its temporary resources after success, failure, timeout or cancellation, with independent reconciliation for controller failure. Apply the same externally enforced isolation and resource limits to both sizes and retain the existing build-accounting contract. Exact provisioning deadline/backoff and live bootstrap timing must be defined and tested in #17.

The account API quote obtained on 2026-09-08 was EUR 0.0088/hour net for CX23 and EUR 0.0312/hour net for CPX22. At one billed hour per VM, 100 CPX22 builds cost EUR 3.12 in compute; 1,000 cost EUR 31.20. These examples exclude addresses, storage, traffic and tax; provisioning, cleanup delays and hourly rounding affect charges. Recheck prices and capacity before creating resources. The fallback applies to disposable builders, not automatic replacement of the long-lived CX33 control and CX43 runtime sizing candidates.

Only consider one unused prewarmed builder after measuring startup delays. That would consume idle budget and still need replenishment; it is not part of the initial implementation.

## Historical assessment

## Finding

**Do not select hosting yet.** AWS ECS Fargate with CodeBuild is the managed baseline, but its documented task metadata endpoint conflicts with the mandatory metadata-denial boundary. A German Hetzner VM running gVisor sandboxes with separate disposable build VMs is a plausible budget candidate, but neither sandbox policy nor procurement has been demonstrated. Managed Kubernetes adds operational work without independently solving isolation.

| Candidate | Documented boundary | Remaining obstacle | Assessment |
| --- | --- | --- | --- |
| ECS Fargate + CodeBuild, Frankfurt | Fargate gives each task an isolated virtual environment; CodeBuild supports remote Docker builds | Fargate supplies task metadata; Docker build privileges and build service credentials require separate containment; deny-public-management-endpoint policy is unresolved | Managed preference, currently fails selection gate |
| EKS + sandboxed workers + isolated builds, Frankfurt | Kubernetes can use sandbox runtimes; namespaces alone are insufficient | Worker sandbox, CNI policy, API denial, upgrades, build isolation and wake controller still required | Reject for this pilot timebox and budget |
| Hetzner CX43 runtime + CX33 control/database + disposable CX23 builders, Germany | gVisor intercepts application system calls; separate provider VMs separate builds from runtime/control hosts | Host firewall, resource enforcement, Dockerfile compatibility, provider availability and complete deployment probe unverified | First alternative to probe; not selected |

Fargate isolation is documented in [AWS security considerations](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html). Its [task metadata documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-metadata.html) explicitly exposes metadata to containers. Removing the task role does not remove metadata. Security groups must not be presumed to intercept task-local traffic, and an application-side proxy is not an enforcement boundary if arbitrary code can bypass it. A successful host-level workaround would need evidence before reconsideration.

For CodeBuild, [Docker/VPC configuration](https://docs.aws.amazon.com/codebuild/latest/userguide/change-project.html) discusses privileged builds. Keep platform-controlled build instructions outside the uploaded context, omit all runtime secrets, isolate each build, and scope any artifact authority to that build. Testing only the eventual HTTP container proves nothing about Dockerfile `RUN` instructions. No claim is made that default CodeBuild configuration satisfies the project's build boundary.

Kubernetes itself recommends considering sandboxing for hostile multi-tenancy in its [multi-tenancy guidance](https://kubernetes.io/docs/concepts/security/multi-tenancy/). For the VM candidate, [gVisor's security model](https://gvisor.dev/docs/architecture_guide/security/) explicitly leaves network policy and resource exhaustion controls to the surrounding system. Use separate per-tool sandboxes, no Docker socket, no host networking, and host-enforced egress filtering. gVisor's [network architecture](https://gvisor.dev/docs/architecture_guide/networking/) supports network namespaces but is not a ready-made private-network deny policy.

## Proposed capacity envelope for evaluation

These are costing assumptions, not new accepted product limits: Linux x86_64; each tool 0.5 CPU and 512 MiB, 1 GiB temporary writes and 128 processes; five active tools; 30 deployed tools; 30 logical PostgreSQL databases at 100 MiB each; ten database connections per tool; one candidate update at a time while the old version remains available. Update candidates cannot admit a sixth independently active tool and must not receive normal user traffic before readiness. Reserve six container allocations: 3 CPUs and 3 GiB plus sandbox overhead. Five creators may each have one build, so reserve five simultaneous disposable builders, each 2 CPUs/4 GiB, with ten-minute execution timeout and 1,000 aggregate monthly build minutes.

CX43 has 8 shared vCPUs, 16 GB RAM and 160 GB disk in the [provider's product listing](https://www.hetzner.com/cloud/cost-optimized/). Reserve 4 GB for host/sandbox overhead and 3 GB for six runtime allocations, leaving 9 GB headroom. A separate CX33 control/database allocation avoids putting database files or encryption keys on the runtime host. Shared CPU capacity is not guaranteed throughput: measure five busy fixtures alongside a startup candidate before accepting these limits.

Budget 30 GB for two image generations per tool (500 MB/image), 10 GB source contexts, 3 GB logical data, 10 GB logs, and 10 GB temporary builder disk per builder. Reserve another 30 GB on the runtime host for image unpacking and temporary writes. Reject or truncate at declared limits; image size, extraction overhead and Docker build cache must be measured. Builders are deleted after export; no shared build cache. Runtime writes disappear on replacement, while database files remain on the control VM disk. This supplies ordinary lifecycle persistence, not recovery from host loss.

Bound runtime logs at 10 MiB/tool/day and build logs at 10 MiB/build; seven-day deletion plus a workspace 10 GB storage bound prevents unbounded retention. Build logs also have a 5 GB aggregate workspace bound independent of build count; drop/truncate further output when reached. Exact minute rounding and reservation accounting belong to the build-accounting contract, not this hosting selection. Runtime secrets are encrypted on the control host with a key outside the database and delivered only to the owning runtime. Encryption implementation and key handling remain unproven.

## Monthly cost model

Use 730 hours, five active tools continuously (no idle-stop discount), one full update allocation continuously reserved, 1,000 build minutes, 100 GB external traffic, 30 secret bundles, existing company domain, no paid support, no free-tier credits, and no committed-use discount. The update allowance is deliberately larger than expected usage.

### VM sandbox candidate

Published US-dollar EU prices from the [15 June 2026 price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/) are CX43 $18.49/month, CX33 $9.99/month and CX23 $0.0104/hour. This uses provider dollar prices, not an assumed currency exchange rate.

| Item | Calculation/assumption | USD/month |
| --- | --- | ---: |
| Runtime host, including update headroom | One CX43 | 18.49 |
| Gateway, controller, PostgreSQL, private registry | One CX33 | 9.99 |
| Five concurrent disposable builders | 1,000 one-minute builds, each VM deleted within one hour; 1,000 rounded VM hours × $0.0104 | 10.40 |
| IPv4 | Planning allowance for two permanent addresses and transient builders; verify quote | 2.00 |
| Database, source, images, bounded logs, encrypted secrets | Included host disks at envelope above; no managed KMS or external log vendor | 0.00 |
| Public traffic | 100 GB within published EU 20 TB host allowance | 0.00 |
| DNS and TLS | Existing company DNS/subdomain and automated certificate; no new domain assumed | 0.00 |
| Independent availability/cost notification delivery | Planning allowance; integration not implemented | 2.00 |
| Unexpected storage/traffic/address charges | Explicit contingency | 10.00 |
| **Estimated infrastructure total** | **Published compute plus stated allowances** | **52.88** |

The [billing FAQ](https://docs.hetzner.com/cloud/billing/faq/) rounds each VM's lifetime up to whole hours, so dividing aggregate build minutes by 60 understates disposable-builder charges. The table models 1,000 one-minute builds, not an accepted build-count limit. For 100 ten-minute builds, builder compute is $1.04; more than 1,000 shorter builds or failed provisioning attempts can cost more than the table. Exact build accounting remains unresolved.

Deletion is essential: stopped VMs remain billable according to the [server FAQ](https://docs.hetzner.com/cloud/servers/faq/). Five additional leaked CX23 builders retained all month add $32.45, making this model approximately $85.33. This sensitivity does not replace cleanup enforcement. Taxes, a newly purchased domain, larger logs/images and different resource needs raise the estimate. At illustrative 20% tax, the $52.88 estimate becomes $63.46. These are planning calculations, not an invoice guarantee.

Procurement is a material blocker: the [cost-optimized product page](https://www.hetzner.com/cloud/cost-optimized/) reported CX43 unavailable when consulted. Do not silently substitute higher-priced machines. Requote an available type and redo capacity/cost checks. Actual account-level creation must confirm availability.

### Managed baseline and Kubernetes comparison

Frankfurt Linux/x86 Fargate rates read from the [AWS regional price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/eu-central-1/index.json) on the research date are $0.04656/vCPU-hour and $0.00511/GiB-hour. Fargate requires at least 1 GiB with 0.5 CPU, so its six reserved allocations exceed the proposed 512 MiB tool limit and cost `6 × 730 × (0.5 × 0.04656 + 1 × 0.00511) = $124.35`. The [pricing page](https://aws.amazon.com/fargate/pricing/) confirms the CPU/memory combinations and included 20 GB ephemeral storage. Further rows below are explicit planning allowances pending a regional calculator export, not verified Frankfurt quotes.

| Item | Monthly assumption | USD/month |
| --- | --- | ---: |
| Fargate runtimes + update candidate | Regional rate calculation above | 124.35 |
| Always-on auth gateway/controller | 0.25 CPU/0.5 GiB at same regional rate | 10.36 |
| CodeBuild | 1,000 min × provisional $0.005/min; verify Frankfurt quote | 5.00 |
| PostgreSQL + persistent disk | Small single-AZ managed database planning allowance | 25.00 |
| Auth ingress/load balancer | Hourly and low-volume processing allowance | 25.00 |
| Internet egress network | One NAT gateway, addresses and processing allowance; no cross-AZ design | 45.00 |
| Images/source/storage requests | 30 GB images + 10 GB contexts, allowance | 5.00 |
| Seven-day bounded logs | Ingestion, retained storage and queries, allowance | 5.00 |
| Runtime secret storage/API | 30 bundles × $0.40 plus calls | 12.10 |
| Public traffic | 100 GB charged conservatively at allowance $0.10/GB | 10.00 |
| DNS/TLS/alerts | Existing domain, managed certificate, billing alerts allowance | 2.00 |
| **Managed planning total** | **Not a procurement quote or proven compliant architecture** | **268.81** |

CodeBuild's [pricing](https://aws.amazon.com/codebuild/pricing/) and [compute types](https://docs.aws.amazon.com/codebuild/latest/userguide/build-env-ref-compute-types.html) require regional/type verification. [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/) lists storage and API charges. [VPC pricing](https://aws.amazon.com/vpc/pricing/) charges NAT separately from data transfer and public addresses. These extras cannot be omitted merely because idle tools stop. This architecture still needs a costed egress enforcement solution; the table is already over target before that unresolved increment, so it is not an upper bound.

[EKS pricing](https://aws.amazon.com/eks/pricing/) adds $0.10/cluster-hour under standard support: $73/month before workers. A comparable EKS/Fargate baseline is therefore at least $341.81 using the allowances above, with additional policy/runtime work unresolved. A VM-worker EKS variant still needs separately quoted EU worker, disk, networking and sandbox costs. Neither is competitive with the proposed VM envelope for this pilot.

## Residency and operational feasibility

For AWS, require `eu-central-1` on builds, execution, ECR images, source buckets, PostgreSQL storage, secrets and log groups; disallow replication/export outside the EU. Region availability is documentation evidence, while resource inventory and configuration exports must establish actual placement. Do not rely on the location of the front-end endpoint.

For Hetzner, pin all three host roles and any future volumes/object storage to Germany, using documented [locations](https://docs.hetzner.com/cloud/general/locations/). Keep registry, uploaded contexts, PostgreSQL, encrypted secrets and logs on those EU disks. A US workspace or developer laptop cannot supply deployment-residency evidence. Provider account/support metadata and creator-selected external API destinations retain the exclusions in ADR 0008.

Engineering estimates, not vendor promises: VM isolation/provisioning/cleanup 3–5 working days; authentication gateway, lifecycle and persistence 3–4 days; CLI, diagnostics, secrets and acceptance checks 3–5 days. Total 9–14 engineering days before adoption observation leaves the two-week delivery claim unproven. Expected recurring operations are 4–8 hours/month for the VM option, 2–4 for managed execution, and 6–10 for Kubernetes; at an illustrative $100/hour these are $400–800, $200–400 and $600–1,000 respectively, explicitly outside infrastructure totals. VM patching, certificate/key rotation, disk pressure, build deletion failures and incident investigation remain operator responsibilities.

The next decision requires a bounded run in the intended EU deployment environment: independently probe build and runtime isolation, positive public/database controls, forbidden private/metadata/management paths, cross-database authentication, five active tools plus update headroom, failure-preserving deployment, and actual resource placement. Record unavailable and inconclusive checks as such. Until those pass and an available-host quote fits the envelope, this research supports a **no-go for infrastructure selection**, not a relaxation of isolation, residency or the spending target.
