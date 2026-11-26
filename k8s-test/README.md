# TaskFlow API: POC deployment

A minimal setup for testing that the application works on Kubernetes.
**Not for production.** It has plain-text passwords, MySQL inside the cluster with no persistent
storage, and a single replica. For production use `k8s/` instead.

| File | What it creates |
|---|---|
| `00-namespace.yaml` | Namespace `taskflow-poc` |
| `01-mysql.yaml` | MySQL 8.4 Deployment + ClusterIP Service `mysql` |
| `02-app-config.yaml` | ConfigMap with all app settings |
| `03-app-deployment.yaml` | The API (1 replica, waits for MySQL, runs migrations on start) |
| `04-app-service.yaml` | Internal LoadBalancer Service (port 80 → 8000) |

## 1. Image

The app image is built and pushed by the GitHub Actions pipeline (`.github/workflows/ci.yml`,
`docker` job) on every push to `main`:

- `ghcr.io/pranavjames/taskflow-api:latest`: used by `03-app-deployment.yaml`
- `ghcr.io/pranavjames/taskflow-api:<git-sha>`: pin to this for reproducible deploys

**One-time step:** GHCR packages are private by default. The manifests use no pull secret, so
make the package public: GitHub → your profile → **Packages** → `taskflow-api` →
**Package settings** → **Change visibility → Public**.

The worker nodes in the private subnets need outbound internet access (a NAT gateway) to pull
from `ghcr.io` and Docker Hub.

MySQL uses the official `mysql:8.4` image from Docker Hub (`docker.io/library/mysql:8.4`).

## 2. Deploy

```bash
kubectl apply -f k8s-test/
kubectl -n taskflow-poc get pods -w          # wait until mysql and taskflow-api are 1/1 Running
```

On first start the API pod waits for MySQL, applies the database migrations, and then starts.

## 3. Create an admin user

```bash
kubectl -n taskflow-poc exec -it deploy/taskflow-api -- \
  python -m app.commands.create_admin --email admin@example.com
```

## 4. Access the API

**From your machine** (works even though the nodes are in private subnets):
```bash
kubectl -n taskflow-poc port-forward svc/taskflow-api 8080:80
# open http://localhost:8080/docs
```

**Through the internal load balancer.** This only works from inside the VPC (a bastion, VPN, or
API Gateway VPC Link):
```bash
kubectl -n taskflow-poc get svc taskflow-api     # EXTERNAL-IP column = internal LB DNS name
curl http://<LB_DNS_NAME>/api/v1/health/ready
```

The private subnets need the tag `kubernetes.io/role/internal-elb=1` for the load balancer to be
created. If `EXTERNAL-IP` stays `<pending>`, run
`kubectl -n taskflow-poc describe svc taskflow-api` to see why.

## Troubleshooting

```bash
kubectl -n taskflow-poc logs deploy/taskflow-api -c wait-for-mysql   # stuck waiting for DB?
kubectl -n taskflow-poc logs deploy/taskflow-api                     # migration / app errors
kubectl -n taskflow-poc logs deploy/mysql
kubectl -n taskflow-poc describe pod -l app=taskflow-api             # ImagePullBackOff etc.
```

## Clean up

```bash
kubectl delete -f k8s-test/
```

## Known POC limitations

- **MySQL data is lost** if the MySQL pod restarts or moves, because it uses `emptyDir`. After
  that, restart the API pod (`kubectl -n taskflow-poc rollout restart deploy/taskflow-api`) so it
  re-creates the tables.
- **Passwords and `SECRET_KEY` are in plain text** in the manifests.
- **One API replica, no autoscaling.**
