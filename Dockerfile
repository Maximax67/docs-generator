# ===== Stage 1: Build frontend =====
FROM node:20-alpine AS frontend-builder

RUN apk add --no-cache git

WORKDIR /frontend

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_FRONTEND_URL
ARG NEXT_PUBLIC_SWAGGER_URL
ARG NEXT_PUBLIC_POSTMAN_URL

ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_FRONTEND_URL=${NEXT_PUBLIC_FRONTEND_URL}
ENV NEXT_PUBLIC_SWAGGER_URL=${NEXT_PUBLIC_SWAGGER_URL}
ENV NEXT_PUBLIC_POSTMAN_URL=${NEXT_PUBLIC_POSTMAN_URL}

RUN git clone --depth 1 https://github.com/Maximax67/docs-generator-frontend .
RUN npm install && npm run build

# ===== Stage 2: Build backend =====
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    HOME=/root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    wget \
    libreoffice-core \
    libreoffice-writer \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    fonts-dejavu-core \
    fonts-liberation \
    fonts-noto \
    hyphen-en-us \
    hyphen-uk \
    cabextract \
    && wget https://ftp.debian.org/debian/pool/contrib/m/msttcorefonts/ttf-mscorefonts-installer_3.8_all.deb \
    && dpkg -i ttf-mscorefonts-installer_3.8_all.deb || true \
    && apt-get install -f -y \
    && fc-cache -f -v \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* ./ttf-mscorefonts-installer_3.8_all.deb

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend-builder /frontend/out ./static

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
