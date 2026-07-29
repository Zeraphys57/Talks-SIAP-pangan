import type { MetadataRoute } from "next";

/**
 * The dashboard is public and worth finding. `/lab` is not.
 *
 * Disallowing it is a courtesy to crawlers, not a security control — the real
 * protection is RLS: an unauthenticated request to the labelling queue returns
 * nothing regardless of who asks (see `siap lab-check`). But a research console
 * and a ground-truth labelling task have no business in a search index, and an
 * indexed `/lab` URL invites strangers to try the sign-in form.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/lab", "/lab/"],
    },
  };
}
