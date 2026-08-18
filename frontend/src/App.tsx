import { Suspense, lazy } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Holdings from './pages/portfolio/Holdings'
import Risk from './pages/portfolio/Risk'
import Realized from './pages/portfolio/Realized'
import Income from './pages/portfolio/Income'
import Journal from './pages/portfolio/Journal'
import Settings from './pages/portfolio/Settings'

// 차트 라이브러리(recharts, lightweight-charts)를 쓰는 페이지만 지연 로딩
const TickerDetail = lazy(() => import('./pages/TickerDetail'))
const PortfolioLayout = lazy(() => import('./pages/portfolio/PortfolioLayout'))
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
            <Suspense fallback={fallback}><PortfolioLayout /></Suspense>}>
            <Route index element={<Holdings />} />
            <Route path="risk" element={<Risk />} />
            <Route path="realized" element={<Realized />} />
            <Route path="income" element={<Income />} />
            <Route path="journal" element={<Journal />} />
            <Route path="settings" element={<Settings />} />
          </Route>
          <Route path="/watchlist" element={
            <Suspense fallback={fallback}><Watchlist /></Suspense>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
