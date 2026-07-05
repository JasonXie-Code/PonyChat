/**
 * Chart.js 管理后台统一深色主题与交互配置
 */
export const ADMIN_CHART_TOOLTIP_STYLE = {
  backgroundColor: 'rgba(15, 23, 42, 0.94)',
  borderColor: '#334155',
  borderWidth: 1,
  titleColor: '#e2e8f0',
  bodyColor: '#94a3b8',
  padding: 10,
  cornerRadius: 8,
}

export function getAdminChartTooltipVars() {
  return {
    '--admin-chart-tooltip-bg': ADMIN_CHART_TOOLTIP_STYLE.backgroundColor,
    '--admin-chart-tooltip-border': ADMIN_CHART_TOOLTIP_STYLE.borderColor,
    '--admin-chart-tooltip-title': ADMIN_CHART_TOOLTIP_STYLE.titleColor,
    '--admin-chart-tooltip-body': ADMIN_CHART_TOOLTIP_STYLE.bodyColor,
    '--admin-chart-tooltip-padding': `${ADMIN_CHART_TOOLTIP_STYLE.padding}px`,
    '--admin-chart-tooltip-radius': `${ADMIN_CHART_TOOLTIP_STYLE.cornerRadius}px`,
  }
}

export function getAdminChartDefaults() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: 'index',
      intersect: false,
    },
    hover: {
      mode: 'index',
      intersect: false,
    },
    plugins: {
      legend: {
        labels: {
          color: '#94a3b8',
          usePointStyle: true,
          padding: 16,
          font: { size: 12 },
        },
      },
      tooltip: {
        backgroundColor: ADMIN_CHART_TOOLTIP_STYLE.backgroundColor,
        borderColor: ADMIN_CHART_TOOLTIP_STYLE.borderColor,
        borderWidth: ADMIN_CHART_TOOLTIP_STYLE.borderWidth,
        titleColor: ADMIN_CHART_TOOLTIP_STYLE.titleColor,
        bodyColor: ADMIN_CHART_TOOLTIP_STYLE.bodyColor,
        padding: ADMIN_CHART_TOOLTIP_STYLE.padding,
        cornerRadius: ADMIN_CHART_TOOLTIP_STYLE.cornerRadius,
        displayColors: true,
      },
    },
    scales: {
      x: {
        ticks: { color: '#94a3b8' },
        grid: { color: 'rgba(148, 163, 184, 0.12)' },
      },
      y: {
        ticks: { color: '#94a3b8' },
        grid: { color: 'rgba(148, 163, 184, 0.12)' },
        beginAtZero: true,
      },
    },
    animation: {
      duration: 400,
      easing: 'easeInOutQuart',
    },
  }
}

/** 折线图数据集默认样式 */
export function lineDatasetStyle(color, fill = true) {
  return {
    borderColor: color,
    backgroundColor: fill ? hexToRgba(color, 0.18) : 'transparent',
    fill,
    tension: 0.35,
    borderWidth: 2,
    pointRadius: 3,
    pointHoverRadius: 7,
    pointHoverBorderWidth: 2,
    pointBackgroundColor: color,
    pointBorderColor: '#0f172a',
  }
}

function hexToRgba(hex, alpha) {
  if (typeof hex !== 'string' || !hex.startsWith('#')) {
    return `rgba(159, 134, 214, ${alpha})`
  }
  const h = hex.slice(1)
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const n = parseInt(full, 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r},${g},${b},${alpha})`
}

/**
 * 在 Chart 构造后调用，设置 canvas 光标
 */
export function attachChartHoverCursor(chart) {
  const canvas = chart?.canvas
  if (!canvas) return () => {}
  const onMove = (e) => {
    const pts = chart.getElementsAtEventForMode(e, 'index', { intersect: false }, false)
    canvas.style.cursor = pts.length ? 'crosshair' : 'default'
  }
  canvas.addEventListener('mousemove', onMove)
  return () => canvas.removeEventListener('mousemove', onMove)
}
