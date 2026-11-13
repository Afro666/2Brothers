FROM docker.io/library/node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_LIVE_BUYER=false
ENV VITE_LIVE_BUYER=$VITE_LIVE_BUYER
RUN npm run build

# Caddy serves the built files. Its config is in the image, so a config change
# rebuilds the image and the container is recreated with it.
FROM docker.io/library/caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
