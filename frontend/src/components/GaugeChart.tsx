interface Props {
  score: number
  light: string
  label: string
  size?: number
}

const LIGHT_COLORS: Record<string, string> = {
  '🟢': '#26a69a',
  '🟢🔴': '#66bb6a',
  '🟡': '#ffa726',
  '🔴🟢': '#ef5350',
  '🔴': '#ef5350',
}

export default function GaugeChart({ score, light, label, size = 120 }: Props) {
  const color = LIGHT_COLORS[light] || '#888ca6'
  const r = 42
  const cx = size / 2
  const cy = size / 2 + 10
  const circumference = Math.PI * r
  const offset = circumference * (1 - Math.min(score, 100) / 100)

  return (
    <div style={{ textAlign: 'center' }}>
      <svg width={size} height={size / 2 + 30} viewBox={`0 0 ${size} ${size / 2 + 30}`}>
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke="#2a2d3a"
          strokeWidth={8}
          strokeLinecap="round"
        />
        {score > 0 && (
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            fill="none"
            stroke={color}
            strokeWidth={8}
            strokeLinecap="round"
            strokeDasharray={`${circumference}`}
            strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 0.5s ease' }}
          />
        )}
        <text x={cx} y={cy - 4} textAnchor="middle" fill="#e4e6f0" fontSize={22} fontWeight={700}>
          {Math.round(score)}
        </text>
        <text x={cx} y={cy + 14} textAnchor="middle" fill={color} fontSize={11}>
          {light}
        </text>
      </svg>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: -4 }}>{label}</div>
    </div>
  )
}
