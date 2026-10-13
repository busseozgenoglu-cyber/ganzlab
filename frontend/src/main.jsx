import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

/** Son çare: uygulamanın tamamı çökerse boş sayfa yerine Türkçe hata ekranı. */
class RootBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) { return { error } }
  componentDidCatch(error, info) { console.error('SesKlon beklenmeyen hata:', error, info?.componentStack) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="app">
        <div className="fullpage">
          <div className="empty big" role="alert">
            <h2>Beklenmeyen bir hata oluştu</h2>
            <p className="muted">Arayüz yüklenirken bir sorun çıktı. Sayfayı yenileyerek tekrar deneyin.</p>
            <p className="small muted">{String(this.state.error?.message || this.state.error)}</p>
            <button type="button" className="btn primary" onClick={() => window.location.reload()}>Sayfayı yenile</button>
          </div>
        </div>
      </div>
    )
  }
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RootBoundary>
      <App />
    </RootBoundary>
  </React.StrictMode>,
)
