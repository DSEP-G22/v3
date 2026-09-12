FROM node:22-alpine AS build
WORKDIR /srv
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /srv
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /srv/.next/standalone ./
COPY --from=build /srv/.next/static .next/static
COPY --from=build /srv/public public
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
