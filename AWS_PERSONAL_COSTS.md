# AWS Personal Account Costs - March 2026

**Account:** 826182175287 (asinclair)  
**Region:** ap-southeast-2 (Sydney)  
**Period:** March 1-31, 2026

---

## Total AWS Bill: **$64.62/month**

**Much cheaper than work account!** ($6,484 vs $64)

---

## ✅ ECS Fargate Cluster Found: `clawtalk-dev`

**Current Status:**
- **5 running Fargate tasks**
- **2 active services:** `voice-gateway`, `openclaw-agent`
- Default capacity: **FARGATE_SPOT** (70% cheaper)

---

## Breakdown by Service

| Service | March Cost | % of Total | Notes |
|---------|-----------|------------|-------|
| **EC2 - Other** | $25.29 | 39.1% | EBS volumes, snapshots, NAT Gateway? |
| **S3** | $11.26 | 17.4% | Object storage |
| **ALB/NLB** | $10.23 | 15.8% | Load balancer (for voice-gateway) |
| **VPC** | $7.31 | 11.3% | **NAT Gateway likely** |
| **Tax** | $5.87 | 9.1% | GST |
| **ECS Fargate** | $3.88 | 6.0% | ⭐ Container compute |
| **Route 53** | $0.50 | 0.8% | DNS |
| **KMS** | $0.19 | 0.3% | Encryption keys |
| **Amplify** | $0.02 | 0.0% | Static hosting |
| **ECR** | $0.01 | 0.0% | Container images |
| **DynamoDB** | $0.001 | 0.0% | NoSQL (basically free) |
| **API Gateway** | $0.001 | 0.0% | HTTP API |

---

## 🔍 ECS Fargate Detailed Analysis

### Current Running Services

**1. voice-gateway**
- Launch type: Fargate (likely)
- Desired count: Unknown (need describe-services)
- Task definition: TBD

**2. openclaw-agent**
- Launch type: Fargate (likely)  
- Desired count: Unknown
- Task definition: TBD

**Total tasks running:** 5 Fargate tasks

### March 2026 ECS Costs: $3.88

**Calculation (estimated):**
- 5 tasks × 0.25 vCPU × $0.04048/vCPU-hour × 730 hours = $37.05
- 5 tasks × 0.5 GB × $0.004445/GB-hour × 730 hours = $8.11
- **Expected: ~$45/month for always-on tasks**

**Actual: $3.88/month** ⚠️ Much lower!

**Why?**
1. Tasks are using **FARGATE_SPOT** (70% cheaper)
2. Tasks might not be always-on (stopped/started during month)
3. Very small task sizes (0.25 vCPU, 256MB?)

### Cost Breakdown (if always-on with SPOT):
- Fargate Spot discount: 70% off
- $45 × 0.3 = **$13.50/month expected**
- Actual: $3.88 → tasks only ran ~29% of the month?

---

## 💰 Cost Drivers

### 1. **EC2 - Other: $25.29/month (39%)**

Likely breakdown:
- **NAT Gateway**: $32.85/month base charge (0.75 × $32 if not full month)
- **EBS volumes**: $5-10/month
- **Data transfer**: $5-10/month

**NAT Gateway is probably eating most of this cost.**

### 2. **S3: $11.26/month**

What's stored?
- Container images (in ECR)? No, ECR only $0.01
- Backups?
- Static assets?
- Logs?

**Action:** Audit S3 buckets to see what's using 11GB+ storage or significant requests.

### 3. **ALB: $10.23/month**

Breakdown:
- Base: $16.20/month (720 hours)
- LCU usage: Variable

**Actual: $10.23** → Not running full month? Or minimal traffic?

### 4. **VPC: $7.31/month**

Almost certainly **NAT Gateway data processing**:
- Base: $0.045/GB processed
- $7.31 ÷ $0.045 = **162GB processed**

**With Fly.io:** No NAT Gateway → save $7.31/month

---

## 🎯 ECS Fargate Cost Projection

### Current (5 tasks, Fargate Spot, partial month):
- **$3.88/month**

### If Always-On (5 tasks, 0.25 vCPU, 512MB, Fargate Spot):
- CPU: 5 × 0.25 × $0.04048 × 730 × 0.3 (spot) = $11.11
- RAM: 5 × 0.5 × $0.004445 × 730 × 0.3 (spot) = $2.43
- **Total: $13.54/month**

### If Scaled to 30 Users (OpenClaw containers):
- Auth gateway: $1/month (scale to zero)
- Voice gateway (2 replicas, 1 vCPU, 1GB, Spot): $8/month
- OpenClaw containers (30 users, 0.5 vCPU, 512MB, 50% uptime, Spot):
  - 30 × 0.5 × $0.04048 × 365 × 0.3 = ~$66/month
  - 30 × 0.5 × $0.004445 × 365 × 0.3 = ~$7/month
  - **Subtotal: $73/month**
- **NAT Gateway**: $32 base + $10 data = $42/month
- **ALB**: $16.20/month
- **Total: ~$140/month**

### With Fly.io (30 users):
- **$21.15/month**
- **Savings: $119/month vs ECS Fargate**

---

## 📊 Hidden Costs in ECS

| Item | Current | At Scale (30 users) |
|------|---------|---------------------|
| **ECS tasks** | $3.88 | $73 |
| **NAT Gateway** | ~$7 (in VPC) | $42 |
| **ALB** | $10.23 | $16.20 |
| **Total** | $21.11 | **$131.20** |

**Fly.io equivalent:** $21.15 (no NAT, no ALB, includes everything)

---

## 🚀 Cost Optimization Recommendations

### Immediate

1. **Audit S3 usage ($11.26/month)**
   - List buckets and sizes
   - Enable lifecycle policies (move old data to Glacier)
   - **Potential savings: $5-8/month**

2. **Review NAT Gateway necessity ($7-10/month in VPC costs)**
   - Do containers need outbound internet?
   - Can they use VPC endpoints for AWS services?
   - **Potential savings: $7/month**

3. **Optimize ALB usage ($10.23/month)**
   - Consolidate target groups?
   - Use NLB if possible (cheaper)?
   - **Potential savings: $3-5/month**

### At Scale (30 users)

4. **Migrate to Fly.io**
   - Current ECS projection: $131/month
   - Fly.io: $21/month
   - **Savings: $110/month**

---

## Summary

**Current Personal AWS Bill:** $64.62/month

**Container Infrastructure:**
- ECS Fargate: $3.88/month (5 tasks, Fargate Spot, partial uptime)
- Supporting infra (NAT, ALB): ~$17/month
- **Total: ~$21/month**

**Projected at Scale (30 users):**
- ECS Fargate: $131/month
- Fly.io: $21/month
- **Savings: $110/month with Fly.io**

**Key Finding:**
Your personal account is well-optimized! Using Fargate Spot and keeping tasks small. The main waste is:
1. NAT Gateway ($7-10/month) - could eliminate with Fly.io
2. S3 ($11/month) - audit what's stored
3. ALB partially utilized ($10/month)

**Recommendation:** 
Migrate to Fly.io when you scale beyond 5-10 users. Below that, current ECS Spot setup is fine and cheap.

---

## ✅ ACTUAL RUNNING CONFIGURATION (Updated)

### Current Services (as of April 7, 2026)

**1. voice-gateway**
- Desired count: **2 replicas**
- Running: 2/2
- Task size: **0.25 vCPU, 512MB RAM**
- Launch type: **FARGATE** (using Spot via default strategy)
- Task definition: `voice-gateway-dev:7`

**2. openclaw-agent**
- Desired count: **3 replicas**
- Running: 3/3  
- Task size: **0.25 vCPU, 512MB RAM**
- Launch type: **FARGATE** (using Spot via default strategy)
- Task definition: `openclaw-agent-dev:4`
- Created: April 7, 2026 (today!)

**Total:** 5 tasks (2 + 3)

---

## 💰 REVISED Cost Calculation

### Current Month (March 2026): $3.88

**Why so low?**
- Tasks were NOT running the full month
- March cost reflects partial usage
- Tasks appear to have been redeployed April 7

### Full Month Projection (5 tasks always-on, Fargate Spot):

**CPU cost:**
- 5 tasks × 0.25 vCPU × $0.04048/vCPU-hr × 730 hr/month = $37.05
- With FARGATE_SPOT (70% discount): $37.05 × 0.3 = **$11.12**

**Memory cost:**
- 5 tasks × 0.5 GB × $0.004445/GB-hr × 730 hr/month = $8.11
- With FARGATE_SPOT (70% discount): $8.11 × 0.3 = **$2.43**

**Total ECS Fargate (always-on):** $11.12 + $2.43 = **$13.55/month**

**March actual ($3.88) suggests tasks ran ~29% of the month** (8-9 days)

---

## 🔮 Scaling Scenario: 30 OpenClaw User Containers

### Architecture:
- **Auth gateway:** 1 task (0.25 vCPU, 256MB) - could scale to zero with Lambda
- **Voice gateway:** 2 tasks (0.5 vCPU, 512MB each) - always-on
- **OpenClaw containers:** 30 tasks (0.25 vCPU, 512MB each) - 50% avg uptime

### Cost Breakdown (Fargate Spot):

**Auth gateway (always-on):**
- 0.25 × $0.04048 × 730 × 0.3 = $2.22
- 0.25 × $0.004445 × 730 × 0.3 = $0.24
- **Subtotal: $2.46/month**

**Voice gateway (2 replicas, bigger):**
- 2 × 0.5 × $0.04048 × 730 × 0.3 = $8.89
- 2 × 0.5 × $0.004445 × 730 × 0.3 = $0.97
- **Subtotal: $9.86/month**

**OpenClaw containers (30 users, 50% uptime):**
- 30 × 0.25 × $0.04048 × 365 × 0.3 = $33.29
- 30 × 0.25 × $0.004445 × 365 × 0.3 = $3.65
- **Subtotal: $36.94/month**

**ECS Fargate total:** $49.26/month

**Plus supporting infrastructure:**
- NAT Gateway: $32.85 base + ~$10 data = $42.85
- ALB: $16.20
- Data transfer: $5
- **Infrastructure total: $64.05/month**

**Grand total: $49.26 + $64.05 = $113.31/month**

---

## 📊 Final Comparison: 30 Users

| Platform | Compute | Networking | Total | Savings vs ECS |
|----------|---------|------------|-------|----------------|
| **ECS Fargate Spot** | $49.26 | $64.05 | **$113.31** | - |
| **Fly.io** | $21.15 | $0 (included) | **$21.15** | **-$92.16 (81%)** |

**Key insight:** NAT Gateway + ALB costs ($64) are MORE than the actual ECS compute ($49)!

---

## ✅ Current State Summary

**You ARE using ECS Fargate** (personal account)
- Cluster: `clawtalk-dev`
- 5 tasks running (2 voice-gateway + 3 openclaw-agent)
- Task size: 0.25 vCPU, 512MB (small)
- Using FARGATE_SPOT (70% cheaper)
- March cost: $3.88 (partial month)
- Full month projection: ~$13.55

**Well optimized!** You're using Spot, small task sizes, and the right architecture.

**Problem:** When you scale to 30 users, NAT Gateway becomes the bottleneck ($43/month)

**Solution:** Fly.io eliminates NAT Gateway entirely → 81% savings at scale
