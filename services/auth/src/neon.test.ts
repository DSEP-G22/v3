import assert from "node:assert/strict";
import { test } from "node:test";

import { parseNeonKey } from "./neon.ts";

const URL_ =
  "postgresql://u:p@ep-x-123-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require";

test("parses psql command with NEON_KEY prefix", () => {
  const d = parseNeonKey(`NEON_KEY = psql '${URL_}'`);
  assert.equal(d.pooled, "postgresql://u:p@ep-x-123-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require");
  assert.equal(d.direct, "postgresql://u:p@ep-x-123.us-east-2.aws.neon.tech/neondb?sslmode=require");
});

test("rejects garbage", () => {
  assert.throws(() => parseNeonKey("nope"));
});
