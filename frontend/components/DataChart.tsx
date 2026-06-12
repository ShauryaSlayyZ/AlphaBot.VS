'use client';

import { useState, useEffect } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Bar, Line, Doughnut } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
);

const formatLabel = (label: any): string => {
  if (label == null) return "";
  let str = String(label).trim();

  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  if (/^(0?[1-9]|1[0-2])$/.test(str)) {
    const idx = parseInt(str, 10) - 1;
    return months[idx] || str;
  }

  const matchYearMonth = str.match(/^(\d{4})-(0[1-9]|1[0-2])$/);
  if (matchYearMonth) {
    const [_, year, month] = matchYearMonth;
    const idx = parseInt(month, 10) - 1;
    return `${months[idx]} ${year}`;
  }

  // snake_case → Title Case  (e.g. "diablo_canyon" → "Diablo Canyon")
  if (str.includes('_')) {
    return str.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  }

  // lowercase single word → Title Case  (e.g. "central" → "Central")
  if (/^[a-z]+$/.test(str)) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  return str;
};

/** Determine the single best chart type for a given result set */
function pickBestChart(
  results: any[],
  labelKey: string | undefined,
  numericKeys: string[],
  isTimeSeries: boolean
): 'line' | 'bar' | 'doughnut' {
  // Time-series data → line chart (best for trends)
  if (isTimeSeries) return 'line';

  // Multiple numeric columns in same row (multi-metric comparison) → grouped bar
  if (numericKeys.length > 1) return 'bar';

  // Small categorical breakdown (≤ 4 items) → doughnut (easy proportion reading)
  if (results.length <= 4 && labelKey) return 'doughnut';

  // Larger categorical breakdown → horizontal bar
  return 'bar';
}

/** Determine the second-best alternative chart type */
function pickAlternativeChart(
  results: any[],
  labelKey: string | undefined,
  numericKeys: string[],
  isTimeSeries: boolean
): 'line' | 'bar' | 'doughnut' {
  // Time-series data → bar chart
  if (isTimeSeries) return 'bar';

  // Multiple numeric columns in same row → line chart
  if (numericKeys.length > 1) return 'line';

  // Small categorical breakdown → bar chart
  if (results.length <= 8 && labelKey) return 'bar';

  // Larger categorical breakdown → line chart
  return 'line';
}

interface DataChartProps {
  results: any[];
  unit: string;
  darkMode?: boolean;
}

export function DataChart({ results, unit, darkMode }: DataChartProps) {
  const [timeAgg, setTimeAgg] = useState<'detailed' | 'yearly'>('detailed');
  const [chartMode, setChartMode] = useState<'best' | 'alternative'>('best');

  useEffect(() => {
    const firstRow = results[0] || {};
    const keys = Object.keys(firstRow);
    const numKeys = keys.filter(key => typeof firstRow[key] === 'number');
    const isMultiYear = numKeys.every(k => /^(19|20)\d{2}$/.test(k)) && numKeys.length > 0;

    if (isMultiYear && numKeys.length > 2) {
      setTimeAgg('yearly');
    } else {
      setTimeAgg('detailed');
    }
    setChartMode('best');
  }, [results]);

  if (!results || results.length === 0) {
    return <p className="text-gray-500 dark:text-slate-400 text-sm">No data to display</p>;
  }

  const firstRow = results[0];
  const keys = Object.keys(firstRow);
  const numericKeys = keys.filter(key => typeof firstRow[key] === 'number');
  const labelKey = keys.find(key => typeof firstRow[key] === 'string');

  // ── Single scalar value ──────────────────────────────────────────────────
  if (results.length === 1 && numericKeys.length === 1) {
    const value = firstRow[numericKeys[0]];
    const metricName = numericKeys[0].replace(/_/g, ' ').toUpperCase();
    return (
      <div className="flex flex-col items-center justify-center py-8">
        <div className="text-5xl font-bold text-gray-900 dark:text-slate-100 mb-2">
          {value.toLocaleString()}
        </div>
        <div className="text-sm text-gray-500 dark:text-slate-400">{unit}</div>
        <div className="text-xs text-gray-400 dark:text-slate-500 mt-1">{metricName}</div>
      </div>
    );
  }

  const isTimeSeries = results.length > 1 && labelKey != null && labelKey.includes('date');
  const isMultiYearComparison = isTimeSeries && numericKeys.length > 0 && numericKeys.every(k => /^(19|20)\d{2}$/.test(k));
  const roundToTwo = (num: number) => Math.round((num + Number.EPSILON) * 100) / 100;

  // ── Time-aggregation (for monthly data spanning multiple years) ───────────
  let displayResults = results;
  let finalLabelKey = labelKey;
  let finalNumericKeys = numericKeys;

  if (isTimeSeries && timeAgg === 'yearly') {
    if (isMultiYearComparison) {
      // Pivot year columns into a single metric trend over years
      const yearlySums: Record<string, number> = {};
      numericKeys.forEach(yr => {
        yearlySums[yr] = 0;
      });
      results.forEach(row => {
        numericKeys.forEach(yr => {
          yearlySums[yr] += (row[yr] || 0);
        });
      });
      
      displayResults = numericKeys.map(yr => ({
        year: yr,
        value: roundToTwo(yearlySums[yr])
      }));
      finalLabelKey = "year";
      finalNumericKeys = ["value"];
    } else if (labelKey) {
      const aggMap = new Map<string, any>();
      results.forEach(r => {
        const yearStr = String(r[labelKey]).substring(0, 4);
        if (!aggMap.has(yearStr)) {
          aggMap.set(yearStr, { [labelKey]: yearStr, ...Object.fromEntries(numericKeys.map(k => [k, 0])) });
        }
        const row = aggMap.get(yearStr);
        numericKeys.forEach(k => { row[k] += (r[k] || 0); });
      });
      displayResults = Array.from(aggMap.values());
    }
  }

  const bestChart = pickBestChart(displayResults, finalLabelKey, finalNumericKeys, isTimeSeries);
  const alternativeChart = pickAlternativeChart(displayResults, finalLabelKey, finalNumericKeys, isTimeSeries);
  const activeChart = chartMode === 'best' ? bestChart : alternativeChart;

  // shared palette - rich and professional
  const borderColors = [
    'rgb(59, 130, 246)', 'rgb(16, 185, 129)', 'rgb(249, 115, 22)',
    'rgb(139, 92, 246)', 'rgb(236, 72, 153)', 'rgb(234, 179, 8)',
    'rgb(20, 184, 166)', 'rgb(239, 68, 68)', 'rgb(99, 102, 241)', 'rgb(168, 85, 247)'
  ];

  // Dynamic colors for dark mode support
  const isDark = !!darkMode;
  const textColor = isDark ? 'rgba(148, 163, 184, 0.9)' : 'rgba(71, 85, 105, 0.9)';
  const gridColor = isDark ? 'rgba(51, 65, 85, 0.35)' : 'rgba(226, 232, 240, 0.8)';
  const legendColor = isDark ? 'rgba(241, 245, 249, 0.9)' : 'rgba(15, 23, 42, 0.9)';

  const scales = {
    x: {
      grid: { color: gridColor },
      ticks: {
        color: textColor,
        font: { family: 'Inter, system-ui, sans-serif', weight: 500, size: 10 }
      }
    },
    y: {
      grid: { color: gridColor },
      ticks: {
        color: textColor,
        font: { family: 'Inter, system-ui, sans-serif', weight: 500, size: 10 }
      }
    }
  };

  // ── Time-agg toggle (only shown when data has detailed dates or is a multi-year comparison) ────────────
  const showAggToggle = isTimeSeries && labelKey && (String(firstRow[labelKey]).length > 4 || isMultiYearComparison);

  const renderVisualizationHeader = () => {
    const hasChartToggle = bestChart !== alternativeChart;
    if (!showAggToggle && !hasChartToggle) return null;

    return (
      <div className="flex items-center justify-between mb-4 border-b border-gray-100 dark:border-slate-800 pb-2.5">
        {/* Left Side: Time Aggregation Toggle */}
        <div>
          {showAggToggle ? (
            <div className="inline-flex bg-gray-100 dark:bg-slate-850 p-0.5 rounded-xl border border-gray-200/50 dark:border-slate-800 shadow-sm">
              <button
                type="button"
                onClick={() => setTimeAgg('detailed')}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                  timeAgg === 'detailed'
                    ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm border border-gray-200/50 dark:border-slate-650/50'
                    : 'text-gray-500 hover:text-gray-700 dark:text-slate-400 dark:hover:text-slate-200'
                }`}
              >
                Detailed Dates
              </button>
              <button
                type="button"
                onClick={() => setTimeAgg('yearly')}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                  timeAgg === 'yearly'
                    ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm border border-gray-200/50 dark:border-slate-650/50'
                    : 'text-gray-500 hover:text-gray-700 dark:text-slate-400 dark:hover:text-slate-200'
                }`}
              >
                Aggregate Yearly
              </button>
            </div>
          ) : (
            <span className="text-xs font-bold text-gray-405 dark:text-slate-500 uppercase tracking-wider">Analysis Chart</span>
          )}
        </div>

        {/* Right Side: Chart Style Toggle */}
        <div>
          {hasChartToggle && (
            <div className="inline-flex bg-gray-100 dark:bg-slate-850 p-0.5 rounded-xl border border-gray-200/50 dark:border-slate-800 shadow-sm">
              <button
                type="button"
                onClick={() => setChartMode('best')}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-1.5 ${
                  chartMode === 'best'
                    ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm border border-gray-200/50 dark:border-slate-650/50'
                    : 'text-gray-500 hover:text-gray-700 dark:text-slate-400 dark:hover:text-slate-200'
                }`}
              >
                {bestChart === 'line' ? '📈' : bestChart === 'bar' ? '📊' : '🍩'}
                {bestChart.charAt(0).toUpperCase() + bestChart.slice(1)} (Best)
              </button>
              <button
                type="button"
                onClick={() => setChartMode('alternative')}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-1.5 ${
                  chartMode === 'alternative'
                    ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm border border-gray-200/50 dark:border-slate-650/50'
                    : 'text-gray-500 hover:text-gray-700 dark:text-slate-400 dark:hover:text-slate-200'
                }`}
              >
                {alternativeChart === 'line' ? '📈' : alternativeChart === 'bar' ? '📊' : '🍩'}
                {alternativeChart.charAt(0).toUpperCase() + alternativeChart.slice(1)} (Alternative)
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  // ── Single-row / multi-metric (e.g. "show all metrics for 2026") ─────────
  if (results.length === 1 && numericKeys.length > 1) {
    const data = {
      labels: numericKeys.map(k => k.replace(/_/g, ' ').toUpperCase()),
      datasets: [{
        label: unit,
        data: numericKeys.map(k => firstRow[k]),
        backgroundColor: activeChart === 'doughnut'
          ? borderColors.map(c => c.replace('rgb', 'rgba').replace(')', ', 0.82)'))
          : activeChart === 'line'
            ? 'rgba(59, 130, 246, 0.08)'
            : borderColors.map(c => c.replace('rgb', 'rgba').replace(')', ', 0.82)')),
        borderColor: activeChart === 'doughnut' ? borderColors : 'rgb(59, 130, 246)',
        borderWidth: activeChart === 'line' ? 2 : 1,
        fill: activeChart === 'line',
        tension: 0.35,
      }],
    };

    const isHorizontalBar = activeChart === 'bar';
    const options = {
      indexAxis: isHorizontalBar ? ('y' as const) : ('x' as const),
      responsive: true,
      maintainAspectRatio: false,
      ...(activeChart !== 'doughnut' ? { scales } : {}),
      plugins: {
        legend: {
          display: activeChart === 'doughnut',
          labels: {
            color: legendColor,
            font: { family: 'Inter, system-ui, sans-serif', weight: 600, size: 11 }
          }
        },
        tooltip: {
          callbacks: {
            label: (c: any) => {
              const val = activeChart === 'doughnut' ? c.parsed : (isHorizontalBar ? c.parsed.x : c.parsed.y);
              return `${c.label}: ${val?.toLocaleString()} ${unit}`;
            }
          }
        },
      },
    };

    return (
      <div className="w-full">
        {renderVisualizationHeader()}
        <div className="h-[390px] flex items-center justify-center">
          {activeChart === 'line'    && <Line     data={data} options={options as any} />}
          {activeChart === 'bar'     && <Bar      data={data} options={options as any} />}
          {activeChart === 'doughnut'&& <Doughnut data={data} options={options as any} />}
        </div>
      </div>
    );
  }

  // ── Multi-row data with a label key ─────────────────────────────────────
  if (displayResults.length >= 1 && finalLabelKey) {
    const labels = displayResults.map(r => formatLabel(r[finalLabelKey]));

    // Build datasets
    const datasets = finalNumericKeys.map((metric, idx) => {
      const color = borderColors[idx % borderColors.length];
      const isLine = activeChart === 'line';
      const bg = isLine
        ? color.replace('rgb', 'rgba').replace(')', ', 0.08)')
        : color.replace('rgb', 'rgba').replace(')', ', 0.82)');
      return {
        label: metric === 'value' ? (unit.toUpperCase() || 'TOTAL') : metric.replace(/_/g, ' ').toUpperCase(),
        data: displayResults.map(r => r[metric]),
        backgroundColor: activeChart === 'doughnut'
          ? borderColors.map(c => c.replace('rgb', 'rgba').replace(')', ', 0.82)'))
          : bg,
        borderColor: activeChart === 'doughnut' ? borderColors : color,
        borderWidth: isLine ? 2 : 1,
        fill: isLine,
        tension: 0.35,
        pointRadius: isLine ? 4 : undefined,
        pointHoverRadius: isLine ? 6 : undefined,
      };
    });

    const chartData = { labels, datasets };

    const baseOptions = {
      responsive: true,
      maintainAspectRatio: false,
      ...(activeChart !== 'doughnut' ? { scales } : {}),
      plugins: {
        legend: {
          display: activeChart === 'doughnut' || activeChart === 'line' || finalNumericKeys.length > 1,
          position: activeChart === 'doughnut' ? ('right' as const) : ('top' as const),
          labels: {
            color: legendColor,
            font: { family: 'Inter, system-ui, sans-serif', weight: 600, size: 11 }
          }
        },
        tooltip: {
          callbacks: {
            label: (c: any) => {
              const val = activeChart === 'doughnut' ? c.parsed : c.parsed.y;
              return `${c.dataset.label || c.label}: ${val?.toLocaleString()} ${unit}`;
            },
          },
        },
      },
    };

    // horizontal bar for large breakdowns, regular vertical for comparisons
    const barOptions = activeChart === 'bar' && displayResults.length > 8
      ? { ...baseOptions, indexAxis: 'y' as const }
      : baseOptions;

    return (
      <div className="w-full">
        {renderVisualizationHeader()}
        <div className="h-[390px] flex items-center justify-center">
          {activeChart === 'line'    && <Line     data={chartData} options={baseOptions as any} />}
          {activeChart === 'bar'     && <Bar      data={chartData} options={barOptions  as any} />}
          {activeChart === 'doughnut'&& <Doughnut data={chartData} options={baseOptions as any} />}
        </div>
      </div>
    );
  }

  // ── Fallback ─────────────────────────────────────────────────────────────
  return (
    <div className="text-gray-700 dark:text-slate-350">
      <pre className="text-xs">{JSON.stringify(results, null, 2)}</pre>
    </div>
  );
}
