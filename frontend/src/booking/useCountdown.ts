import { useEffect, useRef, useState } from 'react'

/**
 * Whole seconds left of `seconds`, counted by this page's own timer. It measures elapsed
 * time with performance.now(), so a phone whose clock is wrong still counts correctly.
 * Calls `onExpire` once, when it reaches zero.
 */
export function useCountdown(seconds: number, onExpire: () => void): number {
  const [remaining, setRemaining] = useState(seconds)
  const onExpireRef = useRef(onExpire)

  useEffect(() => {
    onExpireRef.current = onExpire
  })

  useEffect(() => {
    const started = performance.now()
    const timer = setInterval(() => {
      const left = Math.max(0, seconds - Math.floor((performance.now() - started) / 1000))
      setRemaining(left)
      if (left === 0) {
        clearInterval(timer)
        onExpireRef.current()
      }
    }, 250)
    return () => clearInterval(timer)
  }, [seconds])

  return remaining
}

/** "9:05". */
export function formatCountdown(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
