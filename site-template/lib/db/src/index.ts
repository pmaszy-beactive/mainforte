import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import * as schema from "./schema";

// DATABASE_URL is a Postgres connection string, handed to this container as an env var by the
// Jenkins provisioning job at `docker run` time -- the job creates this site's own role +
// database (via backbone/deploy/scripts/bootstrap-db.sh) before the container ever starts, so
// this is always a real, already-provisioned connection string, never assembled from parts here.
// See PLAN.md's "Per-site Postgres provisioning" section for the full design; this app never
// needs to know the admin credential that created it.
const connectionString = process.env.DATABASE_URL;
if (!connectionString) {
  throw new Error("DATABASE_URL is not set -- this site's container was started without its provisioned database connection string");
}

export const pool = new Pool({ connectionString });

export const db = drizzle(pool, { schema });

export * from "./schema";
