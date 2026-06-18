import { auth } from "@/auth";
import {
  NextResponse,
  type NextRequest,
  type NextFetchEvent,
  type NextMiddleware,
} from "next/server";

// Auth.js middleware: redirect unauthenticated requests to /login (preserving
// the intended destination as callbackUrl). Constructed at module load — this
// wrap is inert until invoked, so it is safe even when auth is unconfigured.
// `auth(...)` is heavily overloaded, so its result is cast to NextMiddleware to
// expose the (request, event) call signature.
const guarded = auth((req) => {
  if (!req.auth) {
    const url = new URL("/login", req.nextUrl.origin);
    url.searchParams.set("callbackUrl", req.nextUrl.pathname + req.nextUrl.search);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}) as unknown as NextMiddleware;

// Gate page routes — but only when auth is configured. With no Google
// credentials (AUTH_SECRET/AUTH_GOOGLE_ID) the app runs unauthenticated,
// mirroring the backend's empty-GoogleClientId behavior. This keeps local
// development and pre-enablement deploys working (otherwise every page would
// redirect to /login where sign-in cannot complete).
export default function middleware(request: NextRequest, event: NextFetchEvent) {
  if (!process.env.AUTH_SECRET || !process.env.AUTH_GOOGLE_ID) {
    return NextResponse.next();
  }
  return guarded(request, event);
}

// Matched routes (auth applies here when enabled). Excluded:
//  - api/auth   : the Auth.js sign-in/callback endpoints
//  - api        : the backend proxy (carries its own Bearer; backend enforces)
//  - login      : the sign-in page itself
//  - help       : public usage guide (viewable before login)
//  - _next, static assets, files with an extension
export const config = {
  matcher: ["/((?!api|login|help|_next/static|_next/image|favicon.ico|.*\\.).*)"],
};
