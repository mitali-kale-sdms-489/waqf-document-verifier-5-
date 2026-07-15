import { useEffect, useRef, useState } from "react";

/**
 * Counts down from `initialSeconds` and calls `onExpire` once it hits zero.
 * In the real backend this should reset on JWT refresh; for the mock auth
 * flow it simply models what someone would see near session end.
 */
export function useSessionTimer(initialSeconds: number, onExpire: () => void) {
  const [secondsLeft, setSecondsLeft] = useState(initialSeconds);
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;

  useEffect(() => {
    const interval = setInterval(() => {
      setSecondsLeft((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          onExpireRef.current();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const minutes = Math.floor(secondsLeft / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (secondsLeft % 60).toString().padStart(2, "0");

  return { secondsLeft, formatted: `${minutes}:${seconds}` };
}
