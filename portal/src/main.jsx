import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './styles.css'

// business.getlovelly.cloud serves the portal at the root; any other host
// (local development, the API host) at /business/.
const basename = window.location.pathname.startsWith('/business') ? '/business' : '/'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
