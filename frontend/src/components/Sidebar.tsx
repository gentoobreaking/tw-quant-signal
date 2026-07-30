import type { Page } from '../types'

const NAV: { page: Page; label: string; icon: string }[] = [
  { page: 'observation', label: '台股訊號觀察', icon: '📊' },
  { page: 'rules', label: '規則與比重管理', icon: '⚙' },
]

export default function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (p: Page) => void }) {
  return (
    <div className="sidebar">
      <h1>台股 AI 訊號</h1>
      {NAV.map(n => (
        <div
          key={n.page}
          className={`nav-item ${page === n.page ? 'active' : ''}`}
          onClick={() => onNavigate(n.page)}
        >
          <span>{n.icon}</span>
          <span>{n.label}</span>
        </div>
      ))}
    </div>
  )
}
