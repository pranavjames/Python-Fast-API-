# Deploying TaskFlow API to Amazon EKS

## Architecture

```
Client ──HTTPS──▶ API Gateway (HTTP API, public)
                      │  throttling, CORS, access logs
                      ▼
                  VPC Link (ENIs in private subnets)
                      │
                      ▼
          Internal NLB  (Service type=LoadBalancer, private subnets)
                      │  target-type=ip, health check /api/v1/health/ready
                      ▼
          taskflow-api pods (Deployment, 3–12 replicas via HPA)
                      │
                      ▼
               Amazon RDS / Aurora MySQL (private)
```

Worker nodes, the NLB and the database all live in **private subnets**. The only public entry
point is API Gateway.

## Layout

```
k8s/
├── base/                          # Environment-agnostic manifests
│   ├── namespace.yaml             # Namespace with "restricted" Pod Security Standard
│   ├── serviceaccount.yaml
│   ├── configmap.yaml             # Non-secret app settings
│   ├── secret.example.yaml        # Template only (NOT applied)
│   ├── external-secret.example.yaml  # Optional: sync secrets from AWS Secrets Manager
│   ├── deployment.yaml            # Probes, resources, security context, zone spreading
│   ├── service.yaml               # Internal NLB via AWS Load Balancer Controller
│   ├── hpa.yaml                   # CPU/memory autoscaling (3–10 by default)
│   ├── pdb.yaml                   # Max 1 pod down during drains/upgrades
│   ├── networkpolicy.yaml         # Default deny + allow NLB→pods, pods→DNS/MySQL
│   ├── migration-job.yaml         # `alembic upgrade head` (Argo CD PreSync hook)
│   └── kustomization.yaml
└── overlays/production/kustomization.yaml   # Image, RDS host, subnets, CIDRs, HPA bounds
infra/aws/api-gateway.yaml         # CloudFormation: HTTP API + VPC Link + NLB integration
```

## Cluster prerequisites

| Component | Why |
|---|---|
| [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/) | Creates the internal NLB from the Service |
| metrics-server | Supplies CPU/memory metrics to the HPA |
| VPC CNI network policy enabled (or Calico/Cilium) | Enforces `networkpolicy.yaml` |
| Private subnets tagged `kubernetes.io/role/internal-elb=1` | NLB subnet discovery (or set explicitly in the overlay) |
| ECR repository `taskflow-api` | Container image |
| RDS/Aurora MySQL 8, security group allowing 3306 from the pod/node subnets | Database |
| *(optional)* External Secrets Operator | Secrets from AWS Secrets Manager |

## Placeholders to fill in

All in `k8s/overlays/production/kustomization.yaml`:

| Placeholder | Example |
|---|---|
| `<ACCOUNT_ID>`, `<REGION>` | `123456789012`, `us-east-1` |
| `<RDS_ENDPOINT>` | `taskflow.cluster-abc.us-east-1.rds.amazonaws.com` |
| `<PRIVATE_SUBNET_ID_A/B/C>` | `subnet-0abc...` |
| `<VPC_CIDR>` | `10.0.0.0/16` |
| `<DB_SUBNETS_CIDR>` | `10.0.200.0/22` |

## Deployment order

```bash
# 1. Build and push the image
aws ecr get-login-password | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com
docker build -t <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/taskflow-api:1.0.0 .
docker push   <ACCOUNT_ID>.dkr.ecr.<REGION>.amazonaws.com/taskflow-api:1.0.0

# 2. Preview what will be applied
kubectl kustomize k8s/overlays/production

# 3. Namespace + secret (secret is created out-of-band, never committed)
kubectl apply -f k8s/base/namespace.yaml
kubectl -n taskflow create secret generic taskflow-api-secrets \
  --from-literal=SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
  --from-literal=MYSQL_USER=taskflow \
  --from-literal=MYSQL_PASSWORD='<db-password>'

# 4. Apply everything (migration Job runs, then pods roll out)
kubectl apply -k k8s/overlays/production
kubectl -n taskflow wait --for=condition=complete job/taskflow-api-migrate --timeout=10m
kubectl -n taskflow rollout status deployment/taskflow-api

# 5. Create the first admin user
kubectl -n taskflow exec -it deploy/taskflow-api -- \
  python -m app.commands.create_admin --email admin@example.com

# 6. Find the internal NLB's listener ARN (wait until the NLB is "active")
LB_ARN=$(aws elbv2 describe-load-balancers --names taskflow-api-internal \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)
LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn "$LB_ARN" \
  --query 'Listeners[?Port==`80`].ListenerArn' --output text)

# 7. Create API Gateway + VPC Link pointing at that listener
aws cloudformation deploy \
  --stack-name taskflow-api-gateway \
  --template-file infra/aws/api-gateway.yaml \
  --parameter-overrides \
      VpcId=<VPC_ID> \
      PrivateSubnetIds=<SUBNET_A>,<SUBNET_B>,<SUBNET_C> \
      VpcCidr=<VPC_CIDR> \
      NlbListenerArn="$LISTENER_ARN" \
      CorsAllowOrigins=https://app.example.com

aws cloudformation describe-stacks --stack-name taskflow-api-gateway \
  --query 'Stacks[0].Outputs'     # → ApiEndpoint
curl "<ApiEndpoint>/api/v1/health/ready"
```

### Subsequent releases

```bash
cd k8s/overlays/production && kustomize edit set image taskflow-api=<ECR_REPO>:<NEW_TAG> && cd -
kubectl -n taskflow delete job taskflow-api-migrate --ignore-not-found   # Jobs are immutable
kubectl apply -k k8s/overlays/production
```

With **Argo CD**, point an `Application` at `k8s/overlays/production`. The migration Job is
already annotated as a `PreSync` hook, so it runs before every sync and the old Job is cleaned
up automatically.

## Design notes

- **No `replicas` in the Deployment.** The HPA owns the replica count. Re-applying the manifests
  won't reset scaling.
- **One uvicorn worker per pod** (`WEB_CONCURRENCY=1`). Scaling happens through pods, so HPA CPU
  metrics reflect real load.
- **Migrations run as a Job, not on pod start** (`RUN_MIGRATIONS=false`). This stops replicas
  from racing each other on schema changes.
- **Graceful shutdown.** `preStop` sleeps 15s while the NLB deregisters the pod IP (30s
  deregistration delay). uvicorn then drains requests for up to 20s, all within the 60s
  `terminationGracePeriodSeconds`.
- **Probes.** Liveness uses `/health/live`, which doesn't depend on the DB, so a database outage
  won't restart every pod. Readiness and the NLB health check use `/health/ready`, which does
  check the DB, so traffic only goes to pods that can serve it.
- **Database connections.** The worst case is `(DB_POOL_SIZE + DB_MAX_OVERFLOW) × maxReplicas`
  = 10 × 12 = 120 connections. Keep this below the RDS `max_connections`.
- **Security.**
  - Containers run as non-root with a read-only root filesystem and all capabilities dropped.
  - The namespace enforces the `restricted` Pod Security Standard.
  - The NLB only accepts traffic from inside the VPC (`loadBalancerSourceRanges`).
  - NetworkPolicies default-deny everything else.
- **TLS.** TLS is terminated at API Gateway. VPC Link → NLB → pod traffic stays inside the VPC
  over HTTP. For end-to-end TLS, add a TLS listener to the NLB
  (`aws-load-balancer-ssl-cert` / `aws-load-balancer-ssl-ports` annotations with an ACM
  certificate) and point the integration at that listener.
- **Custom domain.** Add `AWS::ApiGatewayV2::DomainName` and `ApiMapping` (ACM certificate in the
  same region) and a Route 53 alias record. Then set `DisableExecuteApiEndpoint: true`.
