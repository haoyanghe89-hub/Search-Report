import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/manrope'
import '@fontsource-variable/source-serif-4'
import './index.css'
import './marketpulse.css'
import MarketPulseApp from './MarketPulseApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MarketPulseApp />
  </StrictMode>,
)
