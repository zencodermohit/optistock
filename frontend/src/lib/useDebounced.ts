import { useEffect, useState } from "react";

/**
 * Delay a rapidly-changing value.
 *
 * Search boxes fire on every keystroke. Without this, typing "keyboard" sends
 * eight requests and the answer to the first one may land after the answer to
 * the last, leaving stale results on screen. Waiting for a pause sends one.
 */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    // Cleanup cancels the pending timer, so only the final keystroke survives.
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
