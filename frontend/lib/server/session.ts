import { cache } from "react";
import { auth } from "@/auth";

/**
 * Request-scoped session lookup.
 *
 * `auth()` decodes the session JWT and, when the Google token has expired,
 * performs a blocking refresh request before returning. A single page render
 * touches it once in the layout plus once per server data fetch, so calling
 * `auth()` directly makes one request pay that cost several times over.
 * `cache()` collapses those into one call per request.
 */
export const getSession = cache(() => auth());
