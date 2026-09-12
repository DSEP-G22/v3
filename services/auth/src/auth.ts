import { connect, type NatsConnection } from "@nats-io/transport-node";
import { betterAuth } from "better-auth";
import { admin, jwt } from "better-auth/plugins";
import pg from "pg";

import { parseNeonKey } from "./neon.js";

const BASE_URL = process.env.BETTER_AUTH_URL ?? "http://localhost:8080";

if ((process.env.BETTER_AUTH_SECRET ?? "").length < 32) {
  throw new Error("BETTER_AUTH_SECRET must be set to 32+ chars in .env (openssl rand -base64 32)");
}

export const pool = new pg.Pool({
  connectionString: parseNeonKey(process.env.NEON_KEY ?? "").pooled,
  max: 5,
});

let nats: Promise<NatsConnection> | undefined;
async function publish(subject: string, body: unknown): Promise<void> {
  try {
    nats ??= connect({ servers: process.env.NATS_URL ?? "nats://nats:4222" });
    (await nats).publish(subject, JSON.stringify(body));
  } catch (err) {
    nats = undefined;
    console.error(`publish ${subject} failed`, err);
  }
}

const social: Record<string, { clientId: string; clientSecret: string }> = {};
for (const p of ["google", "github"] as const) {
  const id = process.env[`${p.toUpperCase()}_CLIENT_ID`];
  const secret = process.env[`${p.toUpperCase()}_CLIENT_SECRET`];
  if (id && secret) social[p] = { clientId: id, clientSecret: secret };
}

export const STAFF_ROLES = ["agent", "lead", "admin", "operator"] as const;

export const auth = betterAuth({
  baseURL: BASE_URL,
  basePath: "/api/auth",
  secret: process.env.BETTER_AUTH_SECRET,
  trustedOrigins: [BASE_URL],
  database: pool,
  emailAndPassword: { enabled: true, minPasswordLength: 8 },
  socialProviders: social,
  user: {
    additionalFields: {
      preferredLanguage: { type: "string", required: false, defaultValue: "en", input: true },
    },
  },
  plugins: [
    admin({ defaultRole: "customer", adminRoles: ["admin"] }),
    jwt({
      jwks: { keyPairConfig: { alg: "EdDSA", crv: "Ed25519" } },
      jwt: {
        issuer: BASE_URL,
        audience: BASE_URL,
        expirationTime: "15m",
        // subscriber_id is deliberately absent: the gateway resolves it via Valkey.
        definePayload: ({ user }) => ({
          email: user.email,
          name: user.name,
          role: (user as { role?: string }).role ?? "customer",
        }),
      },
    }),
  ],
  databaseHooks: {
    user: {
      create: {
        after: async (user) => {
          await publish("user.created", { id: user.id, email: user.email, name: user.name });
        },
      },
    },
  },
});
