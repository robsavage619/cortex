const CREAM = '#EDE8DC'
const T = 1.2 // trace stroke width

// Circuit trace helper
function Trace({ x1, y1, x2, y2 }: { x1: number; y1: number; x2: number; y2: number }) {
  return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={CREAM} strokeWidth={T} />
}
function Node({ cx, cy }: { cx: number; cy: number }) {
  return <circle cx={cx} cy={cy} r={2.2} fill={CREAM} />
}

export function CortexWordmark({ height = 38 }: { height?: number }) {
  // ViewBox 520×76. Letters rendered via <text> at fontSize=66 bold,
  // letterSpacing=5. Geist Mono advance ≈ 39.6px/char at 66px, so:
  //   C: x≈8–48   O: x≈53–93   R: x≈98–138
  //   T: x≈143–183 E: x≈188–228 X: x≈233–473
  // (With letterSpacing the SVG engine places x+advance+spacing per glyph)
  // Positions below tuned to those bounds.

  // C inner arc traces — horizontal lines in the C's bowl opening (right side)
  const cTraces = [
    { y: 21, x1: 23, x2: 46 },
    { y: 30, x1: 18, x2: 46 },
    { y: 39, x1: 16, x2: 46 },
    { y: 48, x1: 18, x2: 46 },
    { y: 57, x1: 23, x2: 46 },
  ]

  return (
    <svg
      viewBox="0 0 310 76"
      height={height}
      style={{ width: 'auto', display: 'block' }}
      aria-label="CORTEX"
    >
      {/* ── Wordmark ── */}
      <text
        x="8"
        y="67"
        fontSize="66"
        fontWeight="800"
        fontFamily="'Geist Mono Variable', 'Geist Mono', monospace"
        letterSpacing="3"
        fill={CREAM}
      >
        CORTEX
      </text>

      {/* ── C circuit traces ── */}
      <g>
        {cTraces.map(({ y, x1, x2 }) => (
          <g key={y}>
            <Trace x1={x1} y1={y} x2={x2} y2={y} />
            <Node cx={x2} cy={y} />
          </g>
        ))}
      </g>

      {/* ── X circuit traces ── */}
      {/* X occupies roughly x=234–276 in the rendered text.
          The X's diagonals cross at center ~(255, 38).
          We branch lines off from 4 quadrant positions. */}
      <g>
        {/* Top-left branch — up then left */}
        <Trace x1={241} y1={15} x2={241} y2={8} />
        <Trace x1={237} y1={8} x2={241} y2={8} />
        <Node cx={237} cy={8} />
        <Node cx={241} cy={15} />

        {/* Top-right branch — up then right */}
        <Trace x1={270} y1={15} x2={270} y2={8} />
        <Trace x1={270} y1={8} x2={276} y2={8} />
        <Node cx={276} cy={8} />
        <Node cx={270} cy={15} />

        {/* Bottom-left branch — down then left */}
        <Trace x1={241} y1={62} x2={241} y2={68} />
        <Trace x1={237} y1={68} x2={241} y2={68} />
        <Node cx={237} cy={68} />
        <Node cx={241} cy={62} />

        {/* Bottom-right branch — down then right */}
        <Trace x1={270} y1={62} x2={270} y2={68} />
        <Trace x1={270} y1={68} x2={276} y2={68} />
        <Node cx={276} cy={68} />
        <Node cx={270} cy={62} />

        {/* Center node */}
        <Node cx={255} cy={38} />
      </g>
    </svg>
  )
}
