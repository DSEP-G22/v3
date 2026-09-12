import { serve } from "@hono/node-server";
import { getMigrations } from "better-auth/db/migration";
import { Hono } from "hono";

import { auth } from "./auth.js";
import { seedPersonas, seedStaff } from "./seed.js";

// ponytail: schema migrated at boot (idempotent) instead of in the migrate one-shot, so the
// Better Auth config stays the single source of its own schema.
const { runMigrations } = await getMigrations(auth.options);
await runMigrations();
await seedStaff(process.env.SEED_STAFF_PASSWORD);
await seedPersonas(process.env.SEED_CUSTOMER_PASSWORD);

const app = new Hono();
app.get("/healthz", (c) => c.text("ok"));
app.on(["GET", "POST"], "/api/auth/*", (c) => auth.handler(c.req.raw));

serve({ fetch: app.fetch, port: Number(process.env.PORT ?? 3000) });
console.log("auth: listening");
