/**
 * Browser Supabase client.
 *
 * The anon key is browser-exposed by design; what it can reach is decided by
 * the RLS policies in supabase/migrations/0006_rls.sql, not by this file. The
 * service role key must never appear here — it carries BYPASSRLS and would hand
 * every visitor the raw snapshots and the unblinded ground-truth pool. The
 * assertion below turns that from a convention into a startup failure.
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  throw new Error(
    "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are required. " +
      "Copy web/.env.example to web/.env.local and fill both in.",
  );
}

/**
 * Legacy Supabase keys are unsigned-payload JWTs whose `role` claim says what
 * they are. Reading it costs nothing and catches the one paste that would
 * matter. Newer `sb_publishable_...` keys are opaque and always browser-safe,
 * so there is nothing to check.
 */
function assertNotServiceRole(key: string): void {
  const parts = key.split(".");
  if (parts.length !== 3) return;
  let claims: { role?: string };
  try {
    claims = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return;
  }
  if (claims.role === "service_role") {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_ANON_KEY holds a service_role key. That key bypasses " +
        "every RLS policy and must never be shipped to a browser. Replace it with " +
        "the anon / publishable key and rotate the leaked one.",
    );
  }
}

assertNotServiceRole(anonKey);

export const supabase: SupabaseClient = createClient(url, anonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
  },
});
