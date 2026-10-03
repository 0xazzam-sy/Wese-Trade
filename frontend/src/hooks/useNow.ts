import { useEffect, useState } from 'react';

/** Current time, re-rendering on each whole-second boundary. */
export function useNow(): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const current = new Date();
      setNow(current);
      timer = setTimeout(tick, 1000 - current.getMilliseconds());
    };
    timer = setTimeout(tick, 1000 - new Date().getMilliseconds());
    return () => {
      clearTimeout(timer);
    };
  }, []);

  return now;
}
