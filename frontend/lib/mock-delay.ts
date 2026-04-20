/** Simulate network latency (100-300ms) for mock API routes */
export function mockDelay(): Promise<void> {
  const ms = 100 + Math.random() * 200;
  return new Promise((resolve) => setTimeout(resolve, ms));
}
