FROM docker.io/library/node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_LIVE_BUYER=false
ENV VITE_LIVE_BUYER=$VITE_LIVE_BUYER
# Unset: every screen runs on the mock. The deploy sets both, so the order flow uses the gateway.
ARG VITE_GATEWAY_URL=
ENV VITE_GATEWAY_URL=$VITE_GATEWAY_URL
ARG VITE_USE_MOCKS=true
ENV VITE_USE_MOCKS=$VITE_USE_MOCKS
RUN npm run build

# Caddy serves the built files. Its config is in the image, so a config change
# rebuilds the image and the container is recreated with it.
# Stock Caddy has no rate limiter; this adds the one module the open /api needs.
FROM docker.io/library/caddy:2-builder-alpine AS caddy
# Pinned (#356): the default branch's head on 2026-06-12, the code tonight's images were built from.
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@5625512f24f6f59d6f64fb3aafe5eecff0b286db

FROM docker.io/library/caddy:2-alpine
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
