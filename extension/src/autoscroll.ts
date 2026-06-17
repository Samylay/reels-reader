/**
 * autoscroll.ts — PURE-ish module (uses DOM APIs but no chrome.* APIs).
 * Handles the ~100-post lazy-loaded backlog by scrolling to force IG to load messages.
 */

export interface ScrollOptions {
  maxRounds?: number;
  idleRounds?: number;
  delayMs?: number;
}

export interface ScrollResult {
  rounds: number;
  finalAnchorCount: number;
  stoppedBecause: "idle" | "maxRounds";
}

/**
 * Count post anchors in the given container.
 */
function countAnchors(container: Element): number {
  return container.querySelectorAll(
    'a[href^="/reel/"], a[href^="/reels/"], a[href^="/p/"]'
  ).length;
}

/**
 * Scroll to force Instagram to load DM history. Instagram lazy-loads messages
 * as the user scrolls up. This function repeatedly scrolls the message container
 * toward the top, waits for content to render, and stops when anchor count
 * stabilizes (idleRounds consecutive rounds with no new anchors) or maxRounds hit.
 *
 * @param container - The scrollable message container element
 * @param opts - Scroll configuration options
 */
export async function loadAllMessages(
  container: Element,
  opts: ScrollOptions = {}
): Promise<ScrollResult> {
  const maxRounds = opts.maxRounds ?? 60;
  const idleRounds = opts.idleRounds ?? 3;
  const delayMs = opts.delayMs ?? 700;

  let consecutiveIdle = 0;
  let lastCount = countAnchors(container);
  let round = 0;

  for (round = 0; round < maxRounds; round++) {
    // Scroll to top of container to trigger lazy loading
    container.scrollTop = 0;
    container.scrollIntoView?.({ behavior: "smooth", block: "start" });

    // Wait for IG to load more content
    await new Promise<void>((resolve) => setTimeout(resolve, delayMs));

    const currentCount = countAnchors(container);

    if (currentCount > lastCount) {
      consecutiveIdle = 0;
      lastCount = currentCount;
    } else {
      consecutiveIdle++;
      if (consecutiveIdle >= idleRounds) {
        return {
          rounds: round + 1,
          finalAnchorCount: currentCount,
          stoppedBecause: "idle",
        };
      }
    }
  }

  return {
    rounds: round,
    finalAnchorCount: countAnchors(container),
    stoppedBecause: "maxRounds",
  };
}

/**
 * Find the scrollable message container in the IG DM thread.
 * Returns null if not found.
 */
export function findMessageContainer(): Element | null {
  // IG DM thread typically has a scrollable div with role="main" or similar
  // Try common selectors — these may need tuning on real DOM
  const candidates = [
    document.querySelector('[role="main"] [style*="overflow"]'),
    document.querySelector('[class*="DirectThread"] [class*="scroll"]'),
    document.querySelector('[data-pagelet*="DM"] [style*="overflow"]'),
    // Fallback: any large scrollable area
    Array.from(document.querySelectorAll("div"))
      .filter((el) => {
        const style = window.getComputedStyle(el);
        return (
          (style.overflowY === "auto" || style.overflowY === "scroll") &&
          el.scrollHeight > window.innerHeight
        );
      })
      .sort((a, b) => b.scrollHeight - a.scrollHeight)[0] ?? null,
  ].filter(Boolean);

  return (candidates[0] as Element | undefined) ?? null;
}
