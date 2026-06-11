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
import { Bar, Line, Doughnut, Pie } from 'react-chartjs-2';

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

interface DataChartProps {
  results: any[];
  unit: string;
}

export function DataChart({ results, unit }: DataChartProps) {
  const [chartType, setChartType] = useState<'auto' | 'bar' | 'doughnut' | 'pie' | 'line'>('auto');
  const [timeAgg, setTimeAgg] = useState<'detailed' | 'yearly'>('detailed');

  useEffect(() => {
    setTimeAgg('detailed');
  }, [results]);

  if (!results || results.length === 0) {
    return <p className="text-gray-500 text-sm">No data to display</p>;
  }

  const firstRow = results[0];
  const keys = Object.keys(firstRow);
  const numericKeys = keys.filter(key => typeof firstRow[key] === 'number');
  const labelKey = keys.find(key => typeof firstRow[key] === 'string');

  // Single value display (no chart toggle needed)
  if (results.length === 1 && numericKeys.length === 1) {
    const value = firstRow[numericKeys[0]];
    const metricName = numericKeys[0].replace(/_/g, ' ').toUpperCase();
    
    return (
      <div className="flex flex-col items-center justify-center py-8">
        <div className="text-5xl font-bold text-gray-900 mb-2">
          {value.toLocaleString()}
        </div>
        <div className="text-sm text-gray-500">{unit}</div>
        <div className="text-xs text-gray-400 mt-1">{metricName}</div>
      </div>
    );
  }

  const isTimeSeries = results.length > 1 && labelKey && labelKey.includes('date');
  let defaultType: 'bar' | 'doughnut' | 'line' = 'bar';
  if (isTimeSeries) {
    defaultType = 'line';
  } else if (results.length > 1 && labelKey && results.length <= 8) {
    defaultType = 'doughnut';
  }

  const activeType = chartType === 'auto' ? defaultType : chartType;

  // Process data for time aggregation
  let displayResults = results;
  if (isTimeSeries && timeAgg === 'yearly' && labelKey) {
    const aggMap: Record<string, any> = {};
    results.forEach(r => {
      const dateStr = String(r[labelKey]);
      const yearStr = dateStr.substring(0, 4); // Extract YYYY
      if (!aggMap[yearStr]) {
        aggMap[yearStr] = { [labelKey]: yearStr };
        numericKeys.forEach(k => aggMap[yearStr][k] = 0);
      }
      numericKeys.forEach(k => {
        aggMap[yearStr][k] += (r[k] || 0);
      });
    });
    displayResults = Object.values(aggMap);
  }

  // Render toggle UI
  const renderToggle = () => (
    <div className="flex justify-between items-center mb-4">
      <div>
        {isTimeSeries && (
          <div className="inline-flex bg-gray-100 p-1 rounded-lg">
            <button
              onClick={() => setTimeAgg('detailed')}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${
                timeAgg === 'detailed' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Detailed Dates
            </button>
            <button
              onClick={() => setTimeAgg('yearly')}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${
                timeAgg === 'yearly' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              Aggregate Yearly
            </button>
          </div>
        )}
      </div>
      <div className="inline-flex bg-gray-100 p-1 rounded-lg">
        {['auto', 'bar', 'doughnut', 'pie', 'line'].map(type => (
          <button
            key={type}
            onClick={() => setChartType(type as any)}
            className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-all ${
              chartType === type 
                ? 'bg-white text-blue-600 shadow-sm' 
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {type}
          </button>
        ))}
      </div>
    </div>
  );

  // Define shared colors
  const bgColors = [
    'rgba(59, 130, 246, 0.8)',
    'rgba(16, 185, 129, 0.8)',
    'rgba(249, 115, 22, 0.8)',
    'rgba(139, 92, 246, 0.8)',
    'rgba(236, 72, 153, 0.8)',
    'rgba(234, 179, 8, 0.8)',
    'rgba(20, 184, 166, 0.8)',
    'rgba(239, 68, 68, 0.8)',
    'rgba(99, 102, 241, 0.8)',
    'rgba(168, 85, 247, 0.8)',
  ];
  const borderColors = [
    'rgb(59, 130, 246)',
    'rgb(16, 185, 129)',
    'rgb(249, 115, 22)',
    'rgb(139, 92, 246)',
    'rgb(236, 72, 153)',
    'rgb(234, 179, 8)',
    'rgb(20, 184, 166)',
    'rgb(239, 68, 68)',
    'rgb(99, 102, 241)',
    'rgb(168, 85, 247)',
  ];

  // Multiple metrics for single entity
  if (results.length === 1 && numericKeys.length > 1) {
    const data = {
      labels: numericKeys.map(k => k.replace(/_/g, ' ').toUpperCase()),
      datasets: [{
        label: unit,
        data: numericKeys.map(k => firstRow[k]),
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 1,
      }],
    };

    const options = {
      indexAxis: activeType === 'bar' ? 'y' as const : undefined,
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: activeType === 'doughnut' || activeType === 'pie' ? true : false, position: 'right' as const },
        tooltip: { callbacks: { label: (c: any) => `${c.parsed.toLocaleString()} ${unit}` } },
      },
    };

    return (
      <div className="w-full">
        {renderToggle()}
        <div className="h-80 flex items-center justify-center">
          {activeType === 'bar' && <Bar data={data} options={options as any} />}
          {activeType === 'doughnut' && <Doughnut data={data} options={options as any} />}
          {activeType === 'pie' && <Pie data={data} options={options as any} />}
          {activeType === 'line' && <Line data={data} options={options as any} />}
        </div>
      </div>
    );
  }

  // Data with multiple rows and a label
  if (displayResults.length >= 1 && labelKey) {
    const metric = numericKeys[0];
    
    const data = {
      labels: displayResults.map(r => r[labelKey]),
      datasets: [{
        label: metric.replace(/_/g, ' ').toUpperCase(),
        data: displayResults.map(r => r[metric]),
        backgroundColor: activeType === 'line' ? 'rgba(59, 130, 246, 0.1)' : bgColors,
        borderColor: activeType === 'line' ? 'rgb(59, 130, 246)' : borderColors,
        borderWidth: activeType === 'line' ? 2 : 1,
        fill: activeType === 'line' ? true : false,
        tension: 0.3,
        pointRadius: 4,
      }],
    };

    const options = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { 
          display: activeType === 'doughnut' || activeType === 'pie' || activeType === 'line', 
          position: activeType === 'line' ? 'top' as const : 'right' as const 
        },
        tooltip: {
          callbacks: {
            label: (c: any) => {
              const val = activeType === 'pie' || activeType === 'doughnut' ? c.parsed : c.parsed.y;
              return `${c.label || c.dataset.label}: ${val.toLocaleString()} ${unit}`;
            },
          },
        },
      },
    };

    return (
      <div className="w-full">
        {renderToggle()}
        <div className="h-80 flex items-center justify-center">
          {activeType === 'bar' && <Bar data={data} options={options as any} />}
          {activeType === 'line' && <Line data={data} options={options as any} />}
          {activeType === 'doughnut' && <Doughnut data={data} options={options as any} />}
          {activeType === 'pie' && <Pie data={data} options={options as any} />}
        </div>
      </div>
    );
  }

  // Fallback
  return (
    <div className="text-gray-700">
      <pre className="text-xs">{JSON.stringify(results, null, 2)}</pre>
    </div>
  );
}
