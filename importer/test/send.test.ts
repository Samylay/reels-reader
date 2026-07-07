import { describe, it, expect, afterEach, vi } from "vitest";
import { sendToBackend } from "../src/send.js";
import type { IngestPayload } from "../src/types.js";

const payload: IngestPayload = { posts: [] } as unknown as IngestPayload;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("sendToBackend", () => {
  it("appends /ingest, stripping a trailing slash from the endpoint", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("ok", { status: 200 }));

    const result = await sendToBackend("http://localhost:3000/", payload);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:3000/ingest");
    expect(result).toEqual({ status: 200, body: "ok" });
  });

  it("throws a clear timeout error when the request is aborted", async () => {
    // Simulate fetch that never resolves until its signal aborts.
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          const signal = (init as RequestInit)?.signal;
          signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError"))
          );
        })
    );

    await expect(
      sendToBackend("http://localhost:3000", payload, 10)
    ).rejects.toThrow(/timed out after 10ms/);
  });
});
