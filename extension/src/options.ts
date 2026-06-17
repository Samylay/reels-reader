/**
 * options.ts — Options page for setting the backend endpoint.
 */

const api = (globalThis as unknown as { browser?: typeof chrome }).browser ?? chrome;
const DEFAULT_ENDPOINT = "http://localhost:8787";

async function load(): Promise<void> {
  const stored = await api.storage.local.get("endpoint") as { endpoint?: string };
  const input = document.getElementById("endpoint") as HTMLInputElement;
  input.value = stored.endpoint ?? DEFAULT_ENDPOINT;
}

async function save(): Promise<void> {
  const input = document.getElementById("endpoint") as HTMLInputElement;
  const endpoint = input.value.trim() || DEFAULT_ENDPOINT;
  await api.storage.local.set({ endpoint });

  const status = document.getElementById("save-status")!;
  status.style.display = "block";
  setTimeout(() => { status.style.display = "none"; }, 2000);
}

document.getElementById("save-btn")!.addEventListener("click", () => void save());
void load();
