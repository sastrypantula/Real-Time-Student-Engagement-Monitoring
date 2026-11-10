# Offline Classroom Intelligence Dashboard

## Folder Structure
```
classroom-dashboard/
├── index.html
├── package.json
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
└── src/
    ├── main.jsx
    └── App.jsx        ← (paste Dashboard.jsx content here)
```

## Installation & Setup

```bash
# 1. Create Vite project
npm create vite@latest classroom-dashboard -- --template react
cd classroom-dashboard

# 2. Install dependencies
npm install
npm install recharts
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

# 3. Replace src/App.jsx with the contents of Dashboard.jsx

# 4. Update src/main.jsx
```

### src/main.jsx
```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
ReactDOM.createRoot(document.getElementById('root')).render(<App />)
```

### tailwind.config.js
```js
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

### index.html (add to `<head>`)
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
```

## Run
```bash
npm run dev
```
Open http://localhost:5173

## Features
- ✅ Live updating attention metrics with animated counters
- ✅ Real-time line chart updating every 2.5s
- ✅ Classroom heatmap (5×5 grid) with color-coded student states
- ✅ Pie chart: mood distribution
- ✅ Bar chart: engagement by topic
- ✅ Confusion spike alert (appears when confused > 50%)
- ✅ Optimization metrics panel with live CPU/FPS
- ✅ Session Report with topic confusion rates
- ✅ Privacy badge — fully offline
- ✅ Live clock in navbar
- ✅ Dark mode throughout
- ✅ 4 sidebar pages: Live Dashboard, Session Report, Optimization Metrics, Settings
