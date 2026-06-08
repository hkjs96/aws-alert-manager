import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { SyncProgressModal } from "../SyncProgressModal";

vi.mock("@/lib/api-functions", () => ({
  fetchJobStatus: vi.fn(),
}));
import { fetchJobStatus } from "@/lib/api-functions";

const completed = {
  job_id: "job-1",
  status: "completed",
  total_count: 1,
  completed_count: 1,
  failed_count: 0,
  results: [{ account_id: "1", imported: 0, deleted: 0 }],
};

describe("SyncProgressModal polling", () => {
  beforeEach(() => {
    vi.mocked(fetchJobStatus).mockReset();
    vi.mocked(fetchJobStatus).mockResolvedValue(completed as never);
  });

  // Regression: a new onSuccess reference from a parent re-render (e.g. inline
  // `onSuccess={() => router.refresh()}`) must NOT restart polling. The previous
  // bug kept onSuccess in the effect deps, so completion -> onSuccess ->
  // router.refresh -> re-render -> new onSuccess -> re-subscribe -> re-poll ->
  // completion -> ... looped forever.
  it("stops after completion and does not re-poll when onSuccess identity changes", async () => {
    const onSuccess = vi.fn();
    const onClose = vi.fn();

    const { rerender } = render(
      <SyncProgressModal isOpen jobId="job-1" onClose={onClose} onSuccess={onSuccess} />,
    );

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    const callsAfterCompletion = vi.mocked(fetchJobStatus).mock.calls.length;

    // Parent re-renders with a brand-new onSuccess reference.
    rerender(
      <SyncProgressModal isOpen jobId="job-1" onClose={onClose} onSuccess={() => {}} />,
    );
    await new Promise((r) => setTimeout(r, 80));

    // Polling must not have restarted: no extra fetches, onSuccess called once.
    expect(vi.mocked(fetchJobStatus).mock.calls.length).toBe(callsAfterCompletion);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });
});
