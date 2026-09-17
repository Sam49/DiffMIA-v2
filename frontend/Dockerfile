# ── Build stage ───────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /build

# Install dependencies first for layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build the static bundle. The app talks to the API via relative
# `/api` paths, so no runtime backend URL is baked in — nginx proxies.
COPY frontend/ ./
RUN npm run build

# ── Serve stage ───────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
