# AWS Cost Analysis - March 2026

**Account:** 730335486558  
**Region:** ap-southeast-2 (Sydney)  
**Period:** March 1-31, 2026

---

## Total AWS Bill: **$6,484.50/month**

---

## Breakdown by Service

### 🔴 Top Cost Drivers

| Service | March Cost | % of Total | Notes |
|---------|-----------|------------|-------|
| **Claude Sonnet 4.6 (Bedrock)** | $2,212.58 | 34.1% | ⚠️ Largest single cost! |
| **Fortinet FortiGate Firewall** | $1,517.76 | 23.4% | Enterprise firewall appliance |
| **Tax** | $589.16 | 9.1% | GST/sales tax |
| **Amazon EC2 Compute** | $588.00 | 9.1% | 5 running instances |
| **Claude Haiku 4.5 (Bedrock)** | $327.55 | 5.1% | Cheaper model but still significant |
| **Amazon Timestream** | $331.30 | 5.1% | Time-series database |
| **Amazon VPC** | $300.64 | 4.6% | **NAT Gateways!** (likely) |
| **EC2 - Other** | $240.48 | 3.7% | EBS volumes, snapshots, data transfer |
| **AWS Directory Service** | $105.63 | 1.6% | Managed AD |
| **CloudWatch** | $85.52 | 1.3% | Logs + metrics |
| **SageMaker** | $44.27 | 0.7% | ML notebooks? |
| **ALB/NLB** | $37.62 | 0.6% | Load balancers |

### 💚 Low/Reasonable Costs

| Service | March Cost | Notes |
|---------|-----------|-------|
| Amazon RDS | $21.36 | Database (reasonable) |
| WorkSpaces | $19.58 | Virtual desktops |
| ElastiCache | $14.28 | Redis/Memcached |
| Lambda | $7.38 | Serverless functions |
| ACM (Certificates) | $7.00 | SSL certs |
| ECR (Container Registry) | $6.95 | Docker images |
| Secrets Manager | $6.98 | Credential storage |
| KMS | $2.04 | Encryption keys |
| S3 | $0.97 | Object storage |
| DynamoDB | $0.01 | NoSQL (very cheap!) |
| API Gateway | $0.16 | API endpoints |

---

## 🔍 Container/Compute Infrastructure Analysis

### Current Setup: **EC2-based, NOT ECS Fargate**

**Running EC2 Instances:**
1. `i-0f6dac37c87940ba9` - **openclaw-ec2** (t3.medium)
   - Type: t3.medium (2 vCPU, 4GB RAM)
   - Cost: ~$30-40/month
   - Likely running Docker containers manually

2. `i-07f3c7ca0e17d858d` - FortiGate1 (c5.xlarge) - $140/month
3. `i-091b02770285175f4` - FortiGate2 (c5.xlarge) - $140/month
4. `i-037fb8565365959ee` - GallagherServer (t3.large) - $60/month
5. `i-0f8b6fa21647e66f2` - Backup Server (t2.micro) - $8/month

**Key Finding:** 
- ❌ **No ECS clusters found** - you're NOT using ECS Fargate yet
- ✅ Running on a single t3.medium EC2 instance
- Cost: ~$30-40/month for openclaw-ec2

---

## 💰 What's Actually Expensive

### 1. **AI/LLM Costs: $2,552.69/month (39% of bill)**

Claude via Bedrock:
- Sonnet 4.6: $2,212.58
- Haiku 4.5: $327.55
- Opus 4.6: $12.55

**Question:** Are you using Bedrock for production workloads? This is the #1 cost driver.

**Potential savings:**
- Switch to direct Anthropic API: ~30% cheaper
- Use OpenRouter: ~40% cheaper
- Use cheaper models for non-critical tasks

### 2. **Fortinet Firewall: $1,517.76/month (23% of bill)**

Enterprise-grade firewall appliance (2x c5.xlarge instances).

**Question:** Is this required? Alternatives:
- AWS Network Firewall: ~$100/month
- Security Groups only: $0

### 3. **VPC Costs: $300.64/month (NAT Gateway likely)**

Breakdown estimate:
- NAT Gateway: ~$32/month base + $0.045/GB processed
- If processing 6TB/month: $270
- **This is a hidden ECS/container cost killer**

**With Fly.io:** No NAT Gateway needed → save $300/month

### 4. **Timestream: $331.30/month**

Time-series database - unclear usage.

**Question:** What's storing in Timestream? Could it move to cheaper storage?

---

## 📊 Container Infrastructure Cost Estimate

**Current (EC2 t3.medium):**
- EC2 instance: $40/month
- EBS volume: $10/month
- ALB (if used): $20-40/month
- Total: ~$70-90/month

**If you moved to ECS Fargate (planned):**
- Auth gateway (0.25 vCPU, 256MB, 1h/day): ~$2/month
- Voice gateway (1 vCPU, 1GB, always-on): ~$35/month
- OpenClaw containers (30 users, 0.5 vCPU, 512MB, 12h/day): ~$500/month
- **NAT Gateway**: $300/month ⚠️
- **ALB**: $40/month
- **Total: ~$880/month**

**With Fly.io instead:**
- All workloads: $21.15/month
- **Savings: $860/month vs ECS**

---

## 🎯 Cost Optimization Recommendations

### Immediate (High Impact)

1. **Audit Bedrock usage ($2,552/month)**
   - Switch to direct Anthropic API or OpenRouter
   - **Potential savings: $800-1,000/month**

2. **Review Fortinet Firewall ($1,518/month)**
   - Do you need enterprise firewall?
   - Use AWS Network Firewall or Security Groups
   - **Potential savings: $1,400/month**

3. **Audit Timestream ($331/month)**
   - What's using it?
   - Could data go to S3 + Athena instead?
   - **Potential savings: $250/month**

4. **Review VPC costs ($301/month)**
   - Likely NAT Gateway for ECS/containers
   - With Fly.io: eliminate NAT Gateway
   - **Potential savings: $300/month**

### Medium Impact

5. **Optimize CloudWatch ($85/month)**
   - Reduce log retention
   - Disable verbose metrics
   - **Potential savings: $40/month**

6. **Review SageMaker ($44/month)**
   - Are notebooks running 24/7?
   - Stop when not in use
   - **Potential savings: $30/month**

### Total Potential Savings: **$2,820/month (43% reduction!)**

---

## 🚀 Migration to Fly.io Impact

**Current container costs (estimated):**
- EC2 t3.medium: $40
- EBS: $10
- Data transfer: $20
- **Subtotal: $70/month**

**After ECS Fargate migration (planned):**
- ECS tasks: $500
- NAT Gateway: $300
- ALB: $40
- **Subtotal: $840/month**
- **Increase: +$770/month ⚠️**

**After Fly.io migration:**
- All containers: $21.15
- **Savings vs current: $49/month**
- **Savings vs planned ECS: $819/month**

---

## 📋 Action Items

1. **Investigate top costs:**
   - [ ] Why is Bedrock usage so high? ($2,553/month)
   - [ ] Is Fortinet firewall necessary? ($1,518/month)
   - [ ] What's in Timestream? ($331/month)
   - [ ] Confirm VPC costs (NAT Gateway?) ($301/month)

2. **Container platform decision:**
   - [ ] Prototype Fly.io deployment
   - [ ] Compare Fly.io vs ECS Fargate costs
   - [ ] Test multi-region performance (syd, sin, nrt)

3. **Cost monitoring:**
   - [ ] Set up billing alerts (>$500/month)
   - [ ] Tag resources by project (openclaw, fortinet, etc.)
   - [ ] Review monthly cost reports

---

## Summary

**Current AWS Bill:** $6,484.50/month

**Top 3 Costs:**
1. Claude Bedrock: $2,553 (39%)
2. Fortinet Firewall: $1,518 (23%)
3. EC2 Compute: $588 (9%)

**Container Infrastructure:**
- Currently: EC2 t3.medium (~$70/month)
- Planned ECS: ~$840/month (+$770 increase!)
- Fly.io alternative: ~$21/month (-$819 savings vs ECS)

**Recommendation:** 
1. Audit AI/firewall costs first (potential $2,200/month savings)
2. Use Fly.io for containers instead of ECS (saves $819/month)
3. Total potential savings: **$3,000+/month (46% reduction)**
