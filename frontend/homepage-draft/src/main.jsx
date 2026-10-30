import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import './styles.css';

// Scroll-reveal styles only apply when the browser can reveal them again.
if ('IntersectionObserver' in window) document.documentElement.classList.add('io');

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
