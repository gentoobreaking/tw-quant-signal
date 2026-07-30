import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import Sidebar from './components/Sidebar'
import StockObservation from './pages/StockObservation'
import RulesManagement from './pages/RulesManagement'
import { api } from './api/client'
import type { Page } from './types'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

function AppShell() {
  const [page, setPage] = useState<Page>('observation')
  const [selectedStock, setSelectedStock] = useState<string>('2330')

  const { data: stocks } = useQuery({
    queryKey: ['stocks'],
    queryFn: () => api.listStocks(),
    refetchInterval: 60_000,
  })

  return (
    <div className="app-layout">
      <Sidebar
        page={page}
        onNavigate={setPage}
        stocks={stocks || []}
        selectedStock={selectedStock}
        onSelectStock={setSelectedStock}
      />
      <div className="main-content">
        {page === 'observation' && <StockObservation selectedStockId={selectedStock} />}
        {page === 'rules' && <RulesManagement />}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/*" element={<AppShell />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
