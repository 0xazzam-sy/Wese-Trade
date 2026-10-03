import { cn } from '@/lib/cn';

// Fixed, deterministic node layout (decorative only).
const NODES: readonly [number, number][] = [
  [8, 18],
  [22, 8],
  [35, 26],
  [48, 12],
  [62, 30],
  [76, 14],
  [90, 24],
  [14, 52],
  [30, 64],
  [44, 48],
  [58, 70],
  [72, 54],
  [86, 66],
  [20, 86],
  [52, 90],
  [80, 88],
];
const EDGES: readonly [number, number][] = [
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
  [4, 5],
  [5, 6],
  [0, 7],
  [2, 9],
  [7, 8],
  [8, 9],
  [9, 10],
  [10, 11],
  [11, 12],
  [4, 11],
  [8, 13],
  [10, 14],
  [12, 15],
  [14, 15],
];

/** Subtle connected-node motif. Purely decorative; hidden from assistive tech. */
export function NeuralBackdrop({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid slice"
      className={cn('pointer-events-none absolute inset-0 size-full', className)}
    >
      {EDGES.map(([a, b]) => {
        const [x1, y1] = NODES[a] ?? [0, 0];
        const [x2, y2] = NODES[b] ?? [0, 0];
        return (
          <line
            key={`${a}-${b}`}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke="var(--ns-node-line)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        );
      })}
      {NODES.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 0.3 : 0.2} fill="var(--ns-node)" />
      ))}
    </svg>
  );
}
