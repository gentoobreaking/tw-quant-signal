import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import Sidebar from './components/Sidebar'
import StockObservation from './pages/StockObservation'
import RulesManagement from './pages/RulesManagement'
import type { Page } from './types'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

function AppShell() {
  const [page, setPage] = useState<Page>('observation')
  return (
    <div className="app-layout">
      <Sidebar page={page} onNavigate={setPage} />
      <div className="main-content">
        {page === 'observation' && <StockObservation />}
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
