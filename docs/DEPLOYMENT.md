# Deploying to AWS

Two options, from simplest to most "production".

## Option 1: One EC2 instance with Docker Compose (simplest, free-tier friendly)

1. **Launch an instance:** EC2 → Launch instance → Ubuntu 24.04, `t3.small` or larger (the model trains during the image build and needs ~1 GB RAM). Create a key pair.
2. **Security group:** allow inbound TCP `22` (your IP only), `3000` (dashboard) and `8000` (API).
3. **Install Docker:**
   ```bash
   ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker ubuntu && exit   # log in again afterwards
   ```
4. **Point the dashboard at the server.** In `docker-compose.yml`, set the dashboard build arg
   `VITE_API_URL: http://<EC2_PUBLIC_IP>:8000` and add `http://<EC2_PUBLIC_IP>:3000` to the API's `CORS_ORIGINS`.
5. **Run it:**
   ```bash
   git clone https://github.com/aish-19shanbhag/fraud-scoring-service.git
   cd fraud-scoring-service
   docker compose up --build -d
   ```
6. Open `http://<EC2_PUBLIC_IP>:3000`. **Stop the instance when you're not demoing** so you don't keep paying for it.

Optional polish: an Elastic IP (stable address), a domain, and Caddy or Nginx in front for HTTPS.

## Option 2: Managed services (how a company would run it)

| Component | AWS service |
|---|---|
| API container | ECS Fargate service behind an Application Load Balancer |
| Dashboard | S3 static website + CloudFront (run `npm run build`, upload `dist/`) |
| PostgreSQL | Amazon RDS for PostgreSQL |
| Redis | Amazon ElastiCache for Redis |
| Images | Amazon ECR (push from GitHub Actions) |
| Secrets | AWS Secrets Manager → `DATABASE_URL`, `REDIS_URL` env vars |
| Logs and metrics | CloudWatch |

Steps in short:
1. Create RDS PostgreSQL and ElastiCache Redis in the same VPC.
2. Build and push the backend image to ECR: `docker build -t fraud-api backend/` → `docker tag` → `docker push`.
3. Create an ECS Fargate task with `DATABASE_URL`, `REDIS_URL` and `CORS_ORIGINS`, using `/health` as the load balancer health check.
4. Build the frontend with `VITE_API_URL=https://<api-domain>` and upload `dist/` to S3 behind CloudFront.
5. Optional: extend `.github/workflows/ci.yml` with a deploy job that pushes to ECR and updates the ECS service on every merge to `main`.

## Alternative: Render (no AWS account needed)

Create a PostgreSQL and a Redis (Key Value) instance on Render, then a **Web Service** from the `backend/` folder (Docker) with `DATABASE_URL` and `REDIS_URL` set, and a **Static Site** from `frontend/` with build command `npm install && npm run build`, publish directory `dist`, and `VITE_API_URL` set to the API URL.
