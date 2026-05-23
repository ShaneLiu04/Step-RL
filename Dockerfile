# Step-RL v2.0 Docker Image
# Supports: CPU inference, GPU training (with nvidia-docker), Demo serving
#
# Build:
#   docker build -t step-rl:latest .
#
# Run Demo (CPU):
#   docker run -p 7860:7860 step-rl:latest
#
# Run Training (GPU):
#   docker run --gpus all -v $(pwd)/outputs:/app/outputs step-rl:latest \
#     python -m step_rl.training.sft_warmup --config config.yaml --use_4bit

# --------------------------
# Stage 1: Builder
# --------------------------
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
ENV PATH=/root/.local/bin:$PATH

# Install Playwright browsers
RUN playwright install chromium

# --------------------------
# Stage 2: Runtime
# --------------------------
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy AS runtime

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy Playwright browsers from builder
COPY --from=builder /root/.cache/ms-playwright /home/appuser/.cache/ms-playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

# Copy project code
COPY --chown=appuser:appgroup . .

# Create necessary directories
RUN mkdir -p /app/data/sft /app/data/trajectories /app/checkpoints /app/logs /app/outputs /app/models \
    && chown -R appuser:appgroup /app

# Environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_OFFLINE=0

# Switch to non-root user
USER appuser

# Expose ports for Gradio Demo and FastAPI
EXPOSE 7860 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import step_rl" || exit 1

# Default: show help
CMD ["python", "-c", "print('Step-RL v2.0 Docker Image\\nUsage: docker run -p 7860:7860 step-rl:latest python -m step_rl.demo.demo --config config.yaml --policy <adapter_path>')"]
