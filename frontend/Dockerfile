# --- CineMind frontend (Next.js 15, App Router) ------------------------------
# Multi-stage: deps → build → runtime. The final image is the Next.js
# "standalone" output: a small server bundle with only production deps.
#
# Build args:
#   NEXT_PUBLIC_API_BASE_URL — public URL of the FastAPI backend (baked into
#   the JS bundle at build time; must be the browser-reachable URL).

# --- Stage 1: dependencies ---------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- Stage 2: build ----------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build arg for plain `docker build` (--build-arg NEXT_PUBLIC_API_BASE_URL=...).
# Render can't pass build args from render.yaml — it instead exposes the
# service's environment variables to the Docker build, which `next build`
# reads directly. When neither is set the client code defaults to
# http://localhost:8000 (see src/lib/api.ts).
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- Stage 3: runtime --------------------------------------------------------
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs
COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
