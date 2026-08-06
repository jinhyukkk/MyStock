import { Suspense, lazy } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'

// 차트 라이브러리(recharts, lightweight-charts)를 쓰는 페이지만 지연 로딩
const TickerDetail = lazy(() => import('./pages/TickerDetail'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Watchlist = lazy(() => import('./pages/Watchlist'))

const fallback = <div className="card skeleton" style={{ minHeight: 200 }} />

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/ticker/:symbol" element={
            <Suspense fallback={fallback}><TickerDetail /></Suspense>} />
          <Route path="/portfolio" element={
            <Suspense fallback={fallback}><Portfolio /></Suspense>} />
          <Route path="/watchlist" element={
            <Suspense fallback={fallback}><Watchlist /></Suspense>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
