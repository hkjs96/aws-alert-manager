export { auth as middleware } from "@/auth";

// Gate page routes behind authentication. Excluded:
//  - api/auth   : the Auth.js sign-in/callback endpoints
//  - api        : the backend proxy (carries its own Bearer; backend enforces)
//  - login      : the sign-in page itself
//  - _next, static assets, files with an extension
export const config = {
  matcher: ["/((?!api|login|_next/static|_next/image|favicon.ico|.*\\.).*)"],
};
