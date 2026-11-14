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
# Shown on Settings > Developer. Set by deploy/update.sh; "unknown" in a local build.
ARG VITE_APP_VERSION=
ENV VITE_APP_VERSION=$VITE_APP_VERSION
ARG VITE_GIT_SHA=
ENV VITE_GIT_SHA=$VITE_GIT_SHA
RUN npm run build

# Caddy serves the built files. Its config is in the image, so a config change
# rebuilds the image and the container is recreated with it.
# Stock Caddy has no rate limiter; this adds the one module the open /api needs.
FROM docker.io/library/caddy:2-builder-alpine AS caddy
# Pinned (#356): v0.1.0 is what the unpinned build resolved to (Go's @latest), so nothing changes.
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@v0.1.0

FROM docker.io/library/caddy:2-alpine
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
# A Caddyfile that cannot start fails the build here, so a deploy never replaces the running
# site with one that exits at once. The two values only have to be set; the real ones come at run time.
RUN SITE_ADDRESS=:80 GATEWAY_HUMAN_TOKEN=build-check caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
COPY --from=build /app/dist /srv
