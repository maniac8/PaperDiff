import React from 'react';
import ReactDOM from 'react-dom/client';
import 'katex/dist/katex.min.css';
import './index.css';
import App from './App';

function dismissBootSplash() {
  const splash = document.getElementById('pd-boot-splash');
  const splashStyle = document.getElementById('pd-boot-splash-style');
  if (splash) {
    splash.remove();
  }
  if (splashStyle) {
    splashStyle.remove();
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

requestAnimationFrame(() => {
  dismissBootSplash();
});
