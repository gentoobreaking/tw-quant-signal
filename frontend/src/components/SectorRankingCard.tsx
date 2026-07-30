import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

interface SectorRank {
  sector: string
  count: number
  avg_score: number
  members: { stock_id: string; stock_name: string; score: number }[]
}

export default function SectorRankingCard() {
  const { data, isLoading } = useQuery<SectorRank[]>({
    queryKey: ['sectorRanking'],
    queryFn: () => api.sectorRanking(),
  })

  if (isLoading) return <div className="empty">載入中...</div>
  if (!data || data.length === 0) return null

  return (
    <div className="card">
      <h2>🏭 類股排行</h2>
      <table>
        <thead>
          <tr><th>類股</th><th>檔數</th><th>平均分數</th><th>個股</th></tr>
        </thead>
        <tbody>
          {data.map(sr => (
            <tr key={sr.sector}>
              <td style={{ fontWeight: 600 }}>{sr.sector}</td>
              <td>{sr.count}</td>
              <td className={sr.avg_score >= 60 ? 'text-green' : sr.avg_score >= 40 ? '' : 'text-red'}>{sr.avg_score}</td>
              <td style={{ fontSize: '13px' }}>
                {sr.members.map(m => (
                  <span key={m.stock_id} style={{ marginRight: 12, whiteSpace: 'nowrap' }}>
                    {m.stock_name ?? m.stock_id} <small>({m.score})</small>
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
