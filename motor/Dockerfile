FROM python:3.12-slim
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.14.1
ARG TORCHVISION_VERSION=0.29.1
ENV PYTHONUNBUFFERED=1 PORT=9090 WORKERS=1 THREADS=4
RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir torch==${TORCH_VERSION} torchvision==${TORCHVISION_VERSION} --index-url ${TORCH_INDEX}
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
RUN pip install --no-cache-dir --no-deps "label-studio-ml @ git+https://github.com/HumanSignal/label-studio-ml-backend.git@7b0d01f3593e327ad9cd2a92dbd08aa89f6403f4"
COPY . .
EXPOSE 9090
CMD ["sh", "-c", "gunicorn --preload --bind :$PORT --workers $WORKERS --threads $THREADS --timeout 0 _wsgi:app"]
