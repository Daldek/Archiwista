/**
 * The number of the queue's running jobs next to „Zadania” in the navigation
 * (docs/SPEC.md 6.2; plan v0.4 C13): everyone's jobs, those of projects the
 * session does not see too (ADR-047), read every 5 s while the page is
 * visible.
 */

import { listJobs } from "./api.js";
import { useEffect, useState } from "./ui.js";

const LOOK_MS = 5000;
const LIMIT = 200;

/**
 * The number of running jobs; `0` until the first answer.
 *
 * @returns {number}
 */
export function useRunningJobs() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    let busy = false;
    let timer = null;
    const look = async () => {
      clearTimeout(timer);
      timer = null;
      if (stopped || busy || document.visibilityState !== "visible") return;
      busy = true;
      try {
        const page = await listJobs({ state: "running", limit: LIMIT }, { signal: controller.signal });
        if (!stopped) setCount(page.items.length);
      } catch (error) {
        if (stopped) return;
        if (!error.problem) throw error;
      } finally {
        busy = false;
      }
      if (!stopped) timer = setTimeout(look, LOOK_MS);
    };
    look();
    document.addEventListener("visibilitychange", look);
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
      document.removeEventListener("visibilitychange", look);
    };
  }, []);
  return count;
}
