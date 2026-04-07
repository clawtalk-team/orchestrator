# Container Platform Comparison for ClawTalk

**Date:** 2026-04-07  
**Goal:** Find alternatives to AWS ECS Fargate for three workload types

---

## Workload Requirements

### 1. Auth Gateway (Serverless/Lambda-like)
- Low traffic, sporadic requests
- FastAPI + Python
- DynamoDB access
- Cold starts acceptable (auth is infrequent)

### 2. Voice Gateway (Scaled Pods)
- WebSocket connections (long-lived)
- Multiple replicas for HA
- Sticky sessions required
- Auto-scaling based on connections
- Shared infrastructure (sharded)

### 3. OpenClaw Containers (Per-User Pods)
- 1 container per user
- Long-running (hours to days)
- Isolated but sharing host resources
- Dynamic spin-up/down
- Cost-efficient resource pooling

---

## Platform Comparison

### Option 1: **Fly.io** ⭐ Best Overall

**Architecture:**
- Global edge deployment (30+ regions)
- Machines API (like ECS RunTask)
- Fly Proxy (automatic load balancing + sticky sessions)
- Apps run on shared physical hosts (resource pooling!)

**Workload Fit:**

| Workload | Fit | Implementation | Notes |
|----------|-----|----------------|-------|
| **Auth Gateway** | ✅ Excellent | Fly Machines with `min_machines_running = 0` | Auto-start on request, scale to zero |
| **Voice Gateway** | ✅ Excellent | Fly Apps with `services.concurrency.hard_limit` | Native sticky sessions, WebSocket support |
| **OpenClaw Containers** | ⭐ Perfect | Fly Machines API (programmatic launch) | Per-user machines on shared hosts, pay only when running |

**Pricing (2026):**

| Resource | Cost | Calculation |
|----------|------|-------------|
| **Shared CPU** | $0.0000008/sec ($2.07/month per vCPU) | 1 vCPU × 730h = $2.07 |
| **RAM** | $0.0000002/MB/sec ($0.15/GB/month) | 1GB × 730h = $0.15 |
| **Persistent Volume** | $0.15/GB/month | Optional for state |
| **Bandwidth** | First 100GB free, then $0.02/GB | Generous free tier |

**Example Costs:**

```
Auth Gateway (0.25 vCPU, 256MB RAM, scale to zero):
- Active 1 hour/day: ~$0.05/month
- Requests-based pricing (mostly free tier)

Voice Gateway (2 replicas, 1 vCPU, 512MB each):
- 2 × ($2.07 + $0.08) = $4.30/month

OpenClaw Container (0.5 vCPU, 512MB, 12h/day):
- ($2.07×0.5 + $0.08) × 50% uptime = $0.56/month per user
- 30 users × $0.56 = $16.80/month
```

**Multi-Region:**
- ✅ 30+ regions worldwide
- Automatic geo-routing
- Deploy: `fly regions add syd` (instant)
- Data replication via LiteFS/Tigris

**Pros:**
- ✅ **Resource pooling** - multiple containers share hosts
- ✅ **Scale to zero** for auth gateway
- ✅ **Machines API** - perfect for orchestrator pattern
- ✅ **Native sticky sessions** (Fly Proxy)
- ✅ **Generous free tier** (3 shared-cpu-1x, 3GB RAM total)
- ✅ **Excellent DX** - simple CLI, good docs
- ✅ **No NAT Gateway costs** (vs AWS)

**Cons:**
- ⚠️ No managed DynamoDB (use Tigris or PostgreSQL)
- ⚠️ Smaller than AWS (less mature)
- ⚠️ Occasional regional outages

**Migration Effort:** 🟢 Low
- Dockerfiles work as-is
- Replace boto3 DynamoDB with Tigris SDK
- Use Fly Machines API instead of ECS RunTask

**Verdict:** 🏆 **BEST FIT** - purpose-built for this use case, cheapest, simplest

---

### Option 2: **Railway.app**

**Architecture:**
- Project-based deployment (like Heroku)
- Services run in isolated containers
- Built-in ephemeral disk (10GB)
- Auto-scaling based on CPU/RAM

**Workload Fit:**

| Workload | Fit | Implementation | Notes |
|----------|-----|----------------|-------|
| **Auth Gateway** | ✅ Good | Railway Service with sleep mode | Auto-sleep after 15 min idle |
| **Voice Gateway** | ✅ Good | Railway Service with multiple replicas | WebSocket support, but no built-in sticky sessions |
| **OpenClaw Containers** | ⚠️ OK | API-triggered deployments | Less flexible than Fly Machines, higher overhead |

**Pricing (2026):**

| Plan | Cost | Includes |
|------|------|----------|
| **Hobby** | $5/month | $5 usage credit, then $0.000231/GB-hour RAM |
| **Pro** | $20/month | $20 usage credit, priority support |

**Resource Costs:**
- **RAM:** $0.000231/GB-hour ($0.169/GB/month)
- **CPU:** $0.000463/vCPU-hour ($0.338/vCPU/month)
- **Disk:** Included (10GB ephemeral)

**Example Costs:**

```
Auth Gateway (256MB RAM, 0.25 vCPU, sleep enabled):
- ~$0.10/month (mostly sleeping)

Voice Gateway (2 replicas, 512MB, 1 vCPU each):
- 2 × ($0.169×0.5 + $0.338) = $0.85/month

OpenClaw Container (512MB, 0.5 vCPU, 50% uptime):
- ($0.169×0.5 + $0.338×0.5) × 0.5 = $0.13/month per user
- 30 users × $0.13 = $3.90/month
```

**Multi-Region:**
- ❌ Single region (US West only as of 2024)
- ⚠️ Expanding but not production-ready globally

**Pros:**
- ✅ **Simplest onboarding** - just connect GitHub
- ✅ **Built-in databases** (PostgreSQL, Redis)
- ✅ **Auto-sleep** for low-traffic apps
- ✅ **Very cheap** for small workloads
- ✅ **Good DX** - nice UI, fast deploys

**Cons:**
- ❌ **No multi-region** (deal-breaker for global apps)
- ⚠️ No API for programmatic container launches (vs Fly Machines)
- ⚠️ Limited to 8GB RAM per service
- ⚠️ No sticky session support

**Migration Effort:** 🟡 Medium
- Need to replace DynamoDB with Railway PostgreSQL
- No direct API for orchestrator (would need webhooks)

**Verdict:** 🟡 **GOOD for MVP** - cheap and simple, but single-region is a blocker

---

### Option 3: **Google Cloud Run**

**Architecture:**
- Fully managed serverless containers
- Auto-scaling from 0 to N instances
- Request-based billing (like Lambda)
- Global load balancing built-in

**Workload Fit:**

| Workload | Fit | Implementation | Notes |
|----------|-----|----------------|-------|
| **Auth Gateway** | ⭐ Perfect | Cloud Run service (scale to zero) | Designed for this exact use case |
| **Voice Gateway** | ✅ Good | Cloud Run with min instances = 2 | WebSocket support, session affinity via cookie |
| **OpenClaw Containers** | ⚠️ Moderate | Cloud Run Jobs API | Less flexible than ECS RunTask, 1-hour max execution |

**Pricing (2026):**

| Resource | Cost | Free Tier |
|----------|------|-----------|
| **CPU** | $0.00002400/vCPU-second | 180,000 vCPU-seconds/month |
| **RAM** | $0.00000250/GB-second | 360,000 GB-seconds/month |
| **Requests** | $0.40/million | 2 million/month |

**Example Costs:**

```
Auth Gateway (0.5 vCPU, 512MB, 100 req/day, 500ms avg):
- CPU: 100×30×0.5×0.5 × $0.000024 = $0.018
- RAM: 100×30×0.5×0.5 × $0.0000025 = $0.002
- Requests: 3000 × $0.0000004 = $0.001
- Total: ~$0.02/month (FREE TIER)

Voice Gateway (1 vCPU, 1GB, always-on):
- CPU: 2.6M sec × $0.000024 = $62.40/month
- RAM: 2.6M sec × $0.0000025 = $6.50/month
- Total: $68.90/month (expensive for always-on!)

OpenClaw Container (0.5 vCPU, 512MB, 12h/day):
- CPU: 1.3M×0.5 × $0.000024 = $15.60/month
- RAM: 1.3M×0.5 × $0.0000025 = $1.63/month
- Total: $17.23/month per user ❌ EXPENSIVE
```

**Multi-Region:**
- ✅ 30+ regions
- Automatic global load balancing
- Multi-region deployments: `gcloud run deploy --region us-central1,europe-west1`

**Pros:**
- ✅ **True serverless** - scale to zero automatically
- ✅ **Google network** - excellent global perf
- ✅ **Session affinity** built-in
- ✅ **Generous free tier**
- ✅ **Mature platform**

**Cons:**
- ❌ **EXPENSIVE for always-on** (voice gateway)
- ❌ **VERY expensive for per-user containers** (30 users = $500+/month!)
- ⚠️ 1-hour max execution time for Cloud Run Jobs
- ⚠️ Requires GCP services (Firestore instead of DynamoDB)

**Migration Effort:** 🔴 High
- Rewrite DynamoDB → Firestore
- Rewrite ECS RunTask → Cloud Run Jobs API
- Different IAM/networking model

**Verdict:** ⚠️ **GOOD for auth, BAD for others** - too expensive for long-running workloads

---

### Option 4: **Azure Container Instances (ACI)**

**Architecture:**
- On-demand containers (like ECS Fargate)
- No cluster management
- Fast start times (~3 seconds)
- Integrates with Azure services

**Workload Fit:**

| Workload | Fit | Implementation | Notes |
|----------|-----|----------------|-------|
| **Auth Gateway** | ✅ Good | Azure Container Apps (serverless) | Scale to zero support |
| **Voice Gateway** | ✅ Good | Container Apps with replicas | Session affinity via Azure Front Door |
| **OpenClaw Containers** | ✅ Good | ACI API (on-demand launch) | Similar to ECS RunTask |

**Pricing (2026):**

| Resource | Cost | Notes |
|----------|------|-------|
| **vCPU** | $0.0000125/second ($32.85/month per vCPU) | 15x more expensive than Fly.io! |
| **RAM** | $0.0000014/GB/second ($3.68/GB/month) | 24x more expensive than Fly.io! |

**Example Costs:**

```
Auth Gateway (0.25 vCPU, 256MB, 1h/day active):
- vCPU: 0.25×3600 × $0.0000125 × 30 = $0.34/month
- RAM: 0.25×3600 × $0.0000014 × 30 = $0.04/month
- Total: $0.38/month

Voice Gateway (1 vCPU, 512MB, always-on):
- vCPU: $32.85/month
- RAM: $1.84/month
- Total: $34.69/month per replica × 2 = $69.38/month

OpenClaw Container (0.5 vCPU, 512MB, 12h/day):
- vCPU: 0.5×43200 × $0.0000125 × 30 = $8.10/month
- RAM: 0.5×43200 × $0.0000014 × 30 = $0.91/month
- Total: $9.01/month per user
- 30 users: $270.30/month ❌ VERY EXPENSIVE
```

**Multi-Region:**
- ✅ 60+ regions (most of any cloud)
- Azure Front Door for global routing
- Container Groups can span regions

**Pros:**
- ✅ **Most regions** worldwide
- ✅ **Fast cold starts** (3s)
- ✅ **Good Windows container support**
- ✅ Integrates with Azure AD, Key Vault

**Cons:**
- ❌ **MOST EXPENSIVE** option (3-5x Fly.io)
- ⚠️ Complex pricing model
- ⚠️ Requires Azure ecosystem

**Migration Effort:** 🟡 Medium
- Similar to AWS (IAM, networking concepts)
- Replace DynamoDB with Cosmos DB
- ACI API similar to ECS

**Verdict:** ❌ **TOO EXPENSIVE** - only consider if already on Azure

---

### Option 5: **DigitalOcean App Platform + Kubernetes**

**Architecture:**
- Hybrid: App Platform (PaaS) + Managed Kubernetes (DOKS)
- Simpler than AWS but more control than Heroku
- Good balance for growing apps

**Workload Fit:**

| Workload | Fit | Implementation | Notes |
|----------|-----|----------------|-------|
| **Auth Gateway** | ✅ Good | App Platform (auto-scaling) | No scale-to-zero, but cheap |
| **Voice Gateway** | ✅ Good | DOKS with Ingress + session affinity | Full Kubernetes control |
| **OpenClaw Containers** | ✅ Good | Kubernetes Jobs or Pods API | Flexible, but more complex |

**Pricing (2026):**

**App Platform:**
- **Basic:** $5/month (512MB RAM, shared CPU)
- **Professional:** $12/month (1GB RAM, 1 vCPU)

**Kubernetes (DOKS):**
- **Control Plane:** FREE
- **Worker Nodes:** 
  - Basic (2 vCPU, 2GB): $18/month
  - General Purpose (2 vCPU, 4GB): $24/month

**Example Costs:**

```
Auth Gateway (App Platform Basic):
- $5/month (no scale-to-zero, always on)

Voice Gateway (DOKS with 2 nodes):
- 2 × $18/month = $36/month
- Runs multiple services (voice gateway + future services)

OpenClaw Containers (DOKS):
- Shared across nodes, resource limits per pod
- 30 users on 2 nodes: ~$36/month total
- ~$1.20/month per user (resource pooling!)
```

**Multi-Region:**
- ✅ 15 regions (US, EU, Asia)
- Manual multi-region via separate clusters
- Global Load Balancer: $10/month extra

**Pros:**
- ✅ **Predictable pricing** (flat rate per node)
- ✅ **Resource pooling** on DOKS (like ECS)
- ✅ **Good DX** - simple UI, good docs
- ✅ **Managed PostgreSQL** (replaces DynamoDB)
- ✅ **Free control plane**

**Cons:**
- ⚠️ No scale-to-zero for auth gateway
- ⚠️ Manual multi-region setup (not automatic)
- ⚠️ Kubernetes complexity for orchestrator API
- ⚠️ Fewer regions than AWS/GCP/Azure

**Migration Effort:** 🟡 Medium-High
- Need to learn Kubernetes (if not already)
- Replace DynamoDB with Managed PostgreSQL
- Build orchestrator logic around Kubernetes Jobs API

**Verdict:** 🟡 **SOLID MIDDLE GROUND** - good if you want Kubernetes experience, not the cheapest

---

## Final Ranking

### By Requirements Fit

| Rank | Platform | Auth Gateway | Voice Gateway | OpenClaw Containers | Multi-Region | Overall Score |
|------|----------|--------------|---------------|---------------------|--------------|---------------|
| 🥇 1 | **Fly.io** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **25/25** |
| 🥈 2 | **DigitalOcean** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | **19/25** |
| 🥉 3 | **Railway** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐ | **16/25** |
| 4 | **Google Cloud Run** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | **17/25** |
| 5 | **Azure ACI** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **18/25** |

### By Total Monthly Cost (30 users scenario)

Assuming:
- Auth: 1h/day active
- Voice: 2 replicas, always-on
- OpenClaw: 30 users, 12h/day average

| Rank | Platform | Auth | Voice | 30 OpenClaw Containers | **Total** |
|------|----------|------|-------|------------------------|-----------|
| 🥇 1 | **Fly.io** | $0.05 | $4.30 | $16.80 | **$21.15** ✅ |
| 🥈 2 | **Railway** | $0.10 | $0.85 | $3.90 | **$4.85** ⚠️ (single region) |
| 🥉 3 | **DigitalOcean** | $5.00 | $36.00 | $36.00 (shared) | **$77.00** |
| 4 | **Google Cloud Run** | $0.02 | $68.90 | $516.90 | **$585.82** ❌ |
| 5 | **Azure ACI** | $0.38 | $69.38 | $270.30 | **$340.06** ❌ |

### By Migration Effort

| Rank | Platform | Effort | Key Changes |
|------|----------|--------|-------------|
| 🥇 1 | **Fly.io** | 🟢 Low | DynamoDB → Tigris, ECS → Machines API |
| 🥈 2 | **Railway** | 🟡 Medium | DynamoDB → PostgreSQL, no orchestrator API |
| 🥉 3 | **Azure ACI** | 🟡 Medium | DynamoDB → Cosmos DB, similar to AWS |
| 4 | **DigitalOcean** | 🟡 Medium-High | Learn Kubernetes, rebuild orchestrator |
| 5 | **Google Cloud Run** | 🔴 High | Full GCP rewrite, different patterns |

---

## Recommendation: 🏆 **Fly.io**

**Why Fly.io wins:**

1. **Perfect workload fit:**
   - Scale-to-zero for auth gateway ✅
   - Native sticky sessions for voice gateway ✅
   - Machines API purpose-built for per-user containers ✅

2. **Cheapest by far:**
   - **$21.15/month** vs Railway $4.85 (but single-region) vs DO $77
   - 95% cheaper than Google Cloud Run
   - No hidden costs (NAT Gateway, data transfer in free tier)

3. **Best multi-region:**
   - 30+ regions globally
   - Auto-routing built-in
   - Deploy to Sydney in 30 seconds

4. **Resource pooling:**
   - Multiple containers share physical hosts
   - Like ECS but simpler and cheaper
   - Pay only for actual RAM/CPU used

5. **Lowest migration effort:**
   - Dockerfiles work as-is
   - Simple API (closer to ECS than Kubernetes)
   - Excellent docs + CLI

**Migration checklist:**

- [ ] Replace DynamoDB with Tigris (Fly's S3-compatible object store) or PostgreSQL
- [ ] Replace `ecs.run_task()` with `fly machines create`
- [ ] Replace ALB sticky sessions with Fly Proxy (automatic)
- [ ] Deploy auth-gateway with `fly.toml` scale-to-zero config
- [ ] Test multi-region: `fly regions add syd sin nrt`

**Cost comparison (30 users):**
- **Current AWS estimate:** ~$150-200/month (ECS Fargate + ALB + NAT)
- **Fly.io:** $21.15/month
- **Savings:** ~85-90% 💰

---

## Alternative: Railway for MVP

If you want the **absolute cheapest** and can accept **single-region** (US West only):

**Railway: $4.85/month** (30 users)

Pros:
- ✅ 5x cheaper than Fly.io
- ✅ Simplest setup (just connect GitHub)
- ✅ Built-in PostgreSQL

Cons:
- ❌ Single region (deal-breaker for AU users)
- ⚠️ No orchestrator API (less flexible)

**Use Railway IF:**
- All users are in US West
- MVP only (plan to migrate later)
- You value extreme simplicity over features

**Use Fly.io IF:**
- Global user base (Australia, US, EU)
- Need programmatic container control
- Production-ready architecture

---

## Next Steps

1. **Prototype on Fly.io free tier:**
   - Sign up (no credit card for free tier)
   - Deploy auth-gateway: `fly launch`
   - Test Machines API for orchestrator
   - Verify Sydney region latency

2. **Cost validation:**
   - Run real traffic for 1 week
   - Check actual usage vs estimates
   - Compare to current AWS bill

3. **Migration plan:**
   - Week 1: Auth gateway + DynamoDB → Tigris
   - Week 2: Voice gateway + sticky sessions
   - Week 3: Orchestrator + Machines API
   - Week 4: Multi-region testing (syd, sin, nrt)

Ready to try Fly.io?
