FROM docker.io/library/node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Caddy serves the built files; its config is mounted by deploy/compose.yaml.
FROM docker.io/library/caddy:2-alpine
COPY --from=build /app/dist /srv
