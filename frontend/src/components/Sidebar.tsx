import type { Page, Stock } from '../types'

const NAV: { page: Page; label: string; icon: string }[] = [
  { page: 'observation', label: '台股訊號觀察', icon: '📊' },
  { page: 'rules', label: '規則與比重管理', icon: '⚙' },
]

interface Props {
  page: Page
  onNavigate: (p: Page) => void
  stocks: Stock[]
  selectedStock: string
  onSelectStock: (id: string) => void
}

export default function Sidebar({ page, onNavigate, stocks, selectedStock, onSelectStock }: Props) {
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

      {page === 'observation' && (
        <>
          <div className="sidebar-section-label">個股觀察</div>
          <div className="sidebar-stocks">
            {stocks.map(s => {
              const isActive = selectedStock === s.id
              return (
                <div
                  key={s.id}
                  className={`sidebar-stock-item ${isActive ? 'active' : ''}`}
                  onClick={() => onSelectStock(s.id)}
                >
                  <div className="sidebar-stock-main">
                    <span className="sidebar-stock-id">{s.id}</span>
                    <span className="sidebar-stock-name">{s.name}</span>
                  </div>
                  <div className="sidebar-stock-price">{s.close?.toFixed(1) ?? '-'}</div>
                  <div className="sidebar-stock-row">
                    <span className={s.change_pct != null && s.change_pct >= 0 ? 'text-green' : 'text-red'}>
                      {s.change_pct != null ? `${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%` : '-'}
                    </span>
                    <span className="sidebar-stock-score">
                      {s.health_score != null ? `${s.health_score.toFixed(0)}分` : '-'}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
