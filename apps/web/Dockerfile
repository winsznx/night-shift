# Next.js standalone build for Cloud Run.
#
# npm rather than pnpm inside the container. pnpm 10+ blocks package build scripts by
# default and Next.js needs sharp's; unblocking it requires `pnpm approve-builds`, which
# is interactive and therefore impossible in a container build. npm ci is deterministic
# against package-lock.json and has no such gate. Local development still uses pnpm.

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# NIGHTSHIFT_API_URL is a runtime value: every page is a Server Component that fetches
# on the server, so nothing about the API needs to be baked into the client bundle.
RUN npm run build

FROM node:22-slim AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=8080
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 8080
CMD ["node", "server.js"]
