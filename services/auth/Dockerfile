FROM node:22-alpine AS build
WORKDIR /srv
COPY services/auth/package.json services/auth/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY services/auth/tsconfig.json ./
COPY services/auth/src src
RUN npm run build && npm prune --omit=dev

FROM node:22-alpine
WORKDIR /srv
ENV NODE_ENV=production
COPY --from=build /srv/node_modules node_modules
COPY --from=build /srv/dist dist
COPY services/auth/package.json ./
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD wget -qO- http://127.0.0.1:3000/healthz || exit 1
CMD ["node", "dist/index.js"]
