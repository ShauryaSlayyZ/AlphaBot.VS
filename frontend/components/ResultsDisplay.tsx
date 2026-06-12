import { useRef } from 'react';
import { DataChart } from './DataChart';

const KNOWN_METRICS = [
  'operating_cost',
  'marketing_spend',
  'tax_liability',
  'asset_value',
  'customer_count',
  'revenue',
  'profit',
  'expenses',
  'headcount',
  'salary'
];

function extractMetrics(sql: string, results: any[]): string[] {
  if (!results || results.length === 0) return ['revenue'];

  const sqlLower = (sql || '').toLowerCase();
  const foundMetrics: string[] = [];

  KNOWN_METRICS.forEach(m => {
    const regex = new RegExp(`\\b${m}\\b`, 'i');
    if (regex.test(sqlLower)) {
      foundMetrics.push(m);
    }
  });

  if (foundMetrics.length > 0) {
    return foundMetrics;
  }

  const keys = Object.keys(results[0]);
  const matchedKeys = keys.filter(k => KNOWN_METRICS.includes(k.toLowerCase()));
  if (matchedKeys.length > 0) {
    return matchedKeys;
  }

  const partialMatchedKeys: string[] = [];
  keys.forEach(k => {
    KNOWN_METRICS.forEach(m => {
      if (k.toLowerCase().includes(m)) {
        partialMatchedKeys.push(m);
      }
    });
  });
  if (partialMatchedKeys.length > 0) {
    return Array.from(new Set(partialMatchedKeys));
  }

  const dimensionKeys = [
    'record_date', 'year', 'month', 'plant', 'department', 'region', 
    'comparison_group', 'plant_name', 'id'
  ];
  const numericKeys = keys.filter(k => {
    const val = results[0][k];
    const isNum = typeof val === 'number';
    const isYear = /^(19|20)\d{2}$/.test(k) || (!isNaN(Number(k)) && Number(k) > 1900 && Number(k) < 2100);
    return isNum && !dimensionKeys.includes(k.toLowerCase()) && !isYear;
  });

  if (numericKeys.length > 0) {
    return numericKeys;
  }

  return ['revenue'];
}

interface ResultsDisplayProps {
  data: any;
  devMode: boolean;
  onFollowUpClick: (query: string) => void;
  darkMode?: boolean;
}

export function ResultsDisplay({ data, devMode, onFollowUpClick, darkMode }: ResultsDisplayProps) {
  const summaryRef = useRef<HTMLDivElement>(null);

  if (!data || !data.results) return null;

  const { results, sql_query, unit, plants_queried, insights, metadata, kpis } = data;

  const scrollToSummary = () => {
    summaryRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const formatKPI = (val: any) => {
    if (val == null) return "0";
    if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}M`;
    if (val >= 1000) return `$${(val / 1000).toFixed(1)}K`;
    return val.toLocaleString();
  };

  const formatHeadcount = (val: any) => {
    if (val == null) return "0";
    return val.toLocaleString();
  };

  const formatMetricValue = (val: any, metricName: string) => {
    if (val == null) return "0";
    const isCurrency = !['headcount', 'customer_count', 'customers', 'employees', 'people'].includes(metricName.toLowerCase().replace(/_/g, ' '));
    const prefix = isCurrency ? "$" : "";
    if (val >= 1000000) return `${prefix}${(val / 1000000).toFixed(1)}M`;
    if (val >= 1000) return `${prefix}${(val / 1000).toFixed(1)}K`;
    return prefix + val.toLocaleString();
  };

  const generateExecutiveSummary = () => {
    if (!results || results.length === 0) return "No data available for summary.";
    
    const keys = Object.keys(results[0]);
    const detectedMetrics = extractMetrics(sql_query, results);
    const primaryMetric = detectedMetrics[0] ? detectedMetrics[0].replace(/_/g, ' ') : "data";
    
    const numPlants = plants_queried || 8;
    
    let timeSpan = "the selected timeframe";
    const recordDateKey = keys.find(k => k.includes('date') || k === 'year');
    if (recordDateKey) {
      const years = Array.from(new Set(results.map((r: any) => String(r[recordDateKey]).substring(0, 4))));
      if (years.length > 0) {
        timeSpan = years.join(', ');
      }
    }
    
    let peakInsight = "";
    const dimensionKeys = ['record_date', 'year', 'month', 'plant', 'department', 'region', 'comparison_group', 'plant_name', 'id'];
    const valueKeys = keys.filter(k => {
      const isNum = typeof results[0][k] === 'number';
      return isNum && !dimensionKeys.includes(k.toLowerCase());
    });

    if (valueKeys.length > 0) {
      const labelKey = keys.find(k => typeof results[0][k] === 'string') || 'record_date';
      let maxVal = -Infinity;
      let maxEntity = "";
      let maxKey = "";
      
      results.forEach((row: any) => {
        const entity = row[labelKey] ? row[labelKey].toString() : "";
        valueKeys.forEach(vk => {
          const val = row[vk];
          if (typeof val === 'number' && val > maxVal) {
            maxVal = val;
            maxEntity = entity;
            maxKey = vk;
          }
        });
      });
      
      if (maxVal !== -Infinity) {
        const valFormatted = formatMetricValue(maxVal, primaryMetric);
        const entityPart = maxEntity ? ` observed in ${maxEntity.replace(/_/g, ' ').toUpperCase()}` : "";
        const contextPart = (/^(19|20)\d{2}$/.test(maxKey) || valueKeys.length > 1) ? ` (${maxKey.replace(/_/g, ' ')})` : "";
        peakInsight = `Highest ${primaryMetric}${contextPart} of ${valFormatted}${entityPart}.`;
      }
    }
    
    return `${primaryMetric.charAt(0).toUpperCase() + primaryMetric.slice(1)} analysis completed successfully. ` +
           `Aggregated findings across ${numPlants} power plants. ` +
           `Data span includes ${timeSpan}. ` +
           `${peakInsight}`;
  };

  const getFollowUpQuestions = () => {
    const detectedMetrics = extractMetrics(sql_query, results);
    const m = detectedMetrics[0] || "revenue";
    const cleanM = m.replace(/_/g, ' ');
    const capM = cleanM.charAt(0).toUpperCase() + cleanM.slice(1);
    
    // Extract active filters from SQL query
    const sqlLower = (sql_query || '').toLowerCase();
    const depts = ["sales", "digital", "marketing", "hr", "engineering", "finance", "support", "operations"];
    const regions = ["north", "south", "east", "west", "central"];
    const plants = ["diablo_canyon", "three_mile_island", "palo_verde", "grand_gulf", "vogtle", "hinkley_point", "kashiwazaki", "darlington"];
    
    const activeDept = depts.find(d => sqlLower.includes(`'${d}'`));
    const activeRegion = regions.find(r => sqlLower.includes(`'${r}'`));
    const activePlant = plants.find(p => sqlLower.includes(p));
    
    // Format helpers
    const formatDept = (d: string) => d === "hr" || d === "digital" ? d.toUpperCase() : d.charAt(0).toUpperCase() + d.slice(1);
    const formatRegion = (r: string) => r.charAt(0).toUpperCase() + r.slice(1);
    const formatPlant = (p: string) => p.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    
    const questions = [];
    
    if (activeDept) {
      const dLabel = formatDept(activeDept);
      questions.push(`Compare ${dLabel} and Sales ${capM}`);
      questions.push(`${dLabel} ${capM} Trend`);
      questions.push(`${dLabel} ${capM} by Region`);
      questions.push(`${dLabel} ${capM} by Plant`);
      questions.push(`Top 3 Plants by ${dLabel} ${capM}`);
    } else if (activeRegion) {
      const rLabel = formatRegion(activeRegion);
      questions.push(`${capM} by Department in ${rLabel}`);
      questions.push(`${capM} Trend in ${rLabel}`);
      questions.push(`Compare ${capM} in ${rLabel} and South`);
      questions.push(`${capM} by Plant in ${rLabel}`);
      questions.push(`Top 3 Plants by ${capM} in ${rLabel}`);
    } else if (activePlant) {
      const pLabel = formatPlant(activePlant);
      questions.push(`${capM} by Department in ${pLabel}`);
      questions.push(`${capM} Trend in ${pLabel}`);
      questions.push(`Compare ${pLabel} and Palo Verde ${capM}`);
      questions.push(`Top 3 Performing Plants by ${capM}`);
      questions.push(`${pLabel} ${capM} by Region`);
    } else {
      // General fallbacks
      questions.push(`Compare ${capM} Across Regions`);
      questions.push(`Show ${capM} Trend`);
      questions.push(`Top 3 Performing Plants by ${capM}`);
      questions.push(`Compare ${capM} Across Departments`);
      questions.push(`Compare ${capM} in 2023 and 2024`);
    }
    
    return questions.slice(0, 5);
  };

  return (
    <div className="p-6 space-y-6">
      {/* 1. Contextual KPIs Bar */}
      {kpis && (() => {
        const defaultKeys = ["revenue", "profit", "expenses", "headcount"];
        const dynamicKey = Object.keys(kpis).find(k => !defaultKeys.includes(k));
        
        const fourthKpiName = dynamicKey 
          ? dynamicKey.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
          : "Headcount";
        const fourthKpiVal = dynamicKey ? kpis[dynamicKey] : kpis.headcount;
        const isFourthCurrency = dynamicKey 
          ? !['headcount', 'customer_count'].includes(dynamicKey.toLowerCase()) 
          : false;

        return (
          <div className="grid grid-cols-4 gap-6">
            {[
              { name: "Revenue", val: kpis.revenue, isCurrency: true },
              { name: "Profit", val: kpis.profit, isCurrency: true },
              { name: "Expenses", val: kpis.expenses, isCurrency: true },
              { name: fourthKpiName, val: fourthKpiVal, isCurrency: isFourthCurrency }
            ].map(item => {
              const formattedVal = item.isCurrency ? formatKPI(item.val) : formatHeadcount(item.val);
              return (
                <div key={item.name} className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-5 flex flex-col justify-between transition-all hover:shadow-md">
                  <div>
                    <p className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2">{item.name}</p>
                    <p className="text-3xl font-extrabold text-gray-900 dark:text-slate-50 tracking-tight">{formattedVal}</p>
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}

      {/* 2. Main Visualization */}
      <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-6">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-slate-100 mb-4">Visualization</h3>
        <div className="flex items-center justify-center">
          <DataChart results={results} unit={unit} darkMode={darkMode} />
        </div>
      </div>

      {/* Animated scroll indicator placed outside and below the card */}
      <div 
        onClick={scrollToSummary}
        className="flex flex-col items-center justify-center py-2 text-slate-400 dark:text-slate-500 cursor-pointer group hover:text-blue-500 transition-colors animate-pulse"
      >
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500 group-hover:text-blue-500 transition-colors">
          Scroll for Executive Summary & Data Table
        </span>
        <svg className="w-3.5 h-3.5 mt-0.5 text-slate-400 dark:text-slate-500 group-hover:text-blue-500 transition-colors animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {/* 3. Executive Summary & 4. Results Table */}
      <div ref={summaryRef} className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Executive Summary */}
        <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 shadow-sm rounded-2xl p-6 md:col-span-1 flex flex-col">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-slate-100 mb-3">Executive Summary</h3>
          <div className="flex-1 bg-gray-50/50 dark:bg-slate-950/20 border border-gray-100/50 dark:border-slate-800/80 rounded-2xl p-5 text-sm leading-relaxed text-gray-600 dark:text-slate-300 font-medium">
            {generateExecutiveSummary()}
          </div>
        </div>

        {/* Results Table */}
        <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 shadow-sm rounded-2xl p-6 md:col-span-2 flex flex-col">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-slate-100 mb-3">Data Table</h3>
          <div className="flex-1 overflow-auto rounded-xl border border-gray-100 dark:border-slate-800 max-h-60">
            <table className="w-full text-xs text-left">
              <thead className="bg-gray-50/80 dark:bg-slate-850/50 sticky top-0 font-bold border-b border-gray-100 dark:border-slate-800">
                <tr>
                  {Object.keys(results[0] || {}).map((key) => (
                    <th key={key} className="py-3 px-4 text-gray-500 dark:text-slate-400 font-bold uppercase tracking-wider text-[10px]">
                      {key.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-slate-800 bg-white dark:bg-slate-900">
                {results.map((row: any, idx: number) => (
                  <tr key={idx} className="hover:bg-gray-50/40 dark:hover:bg-slate-850/30 transition-colors">
                    {Object.values(row).map((value: any, cellIdx: number) => (
                      <td key={cellIdx} className="py-3 px-4 text-gray-900 dark:text-slate-200 font-medium">
                        {typeof value === 'number' ? value.toLocaleString() : value}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>



      {/* 6. Developer Mode Panel */}
      {devMode && (
        <div className="space-y-6 pt-6 border-t border-gray-150 dark:border-slate-800 mt-8">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-bold text-gray-400 dark:text-slate-550 uppercase tracking-wider">Developer Diagnostics</h3>
            <span className="px-2 py-0.5 bg-blue-50 dark:bg-blue-950/20 text-blue-700 dark:text-blue-400 text-[10px] font-bold rounded-full border border-blue-100/30 dark:border-blue-900/30">Dev Mode Active</span>
          </div>
          
          <div className="grid grid-cols-4 gap-4">
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-4 flex flex-col justify-center">
              <p className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-1">Execution Mode</p>
              <p className="text-base font-bold text-gray-800 dark:text-slate-200">
                {metadata?.parsed_deterministically ? "⚡ Deterministic" : "🤖 Ollama LLM"}
              </p>
            </div>
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-4 flex flex-col justify-center">
              <p className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-1">Cache Type</p>
              <p className="text-base font-bold text-gray-800 dark:text-slate-200">
                {metadata?.cache_hit ? "✅ Result Cache" : metadata?.used_semantic_cache ? "🧠 Semantic Cache" : "❌ Cold DB Fetch"}
              </p>
            </div>
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-4 flex flex-col justify-center">
              <p className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-1">Parser Confidence</p>
              <p className="text-base font-bold text-gray-800 dark:text-slate-200">
                {metadata?.parser_confidence != null ? `${Math.round(metadata.parser_confidence * 100)}%` : "N/A"}
              </p>
            </div>
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-4 flex flex-col justify-center">
              <p className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-1">Latency / Nodes</p>
              <p className="text-base font-bold text-gray-800 dark:text-slate-200">
                {Math.round(metadata?.backend_ms || 0)}ms / {plants_queried} Nodes
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4">
            <div className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-6 flex flex-col">
              <h3 className="text-xs font-bold text-gray-900 dark:text-slate-100 mb-3">Generated SQL</h3>
              <div className="bg-gray-50 dark:bg-slate-950 border border-gray-100 dark:border-slate-850 rounded-xl p-4 overflow-x-auto max-h-60">
                <pre className="text-xs leading-relaxed text-gray-800 dark:text-slate-350 font-mono">
                  {sql_query.split('\n').map((line: string, i: number) => (
                    <div key={i} className="flex">
                      <span className="w-6 text-gray-400 dark:text-slate-600 select-none mr-2">{i + 1}</span>
                      <span dangerouslySetInnerHTML={{
                        __html: line
                          .replace(/(SELECT|FROM|WHERE|GROUP BY|ORDER BY|AND|OR|AS|SUM)/g, '<span class="text-blue-600 dark:text-blue-400 font-semibold">$1</span>')
                          .replace(/('[^']*')/g, '<span class="text-emerald-600 dark:text-emerald-400">$1</span>')
                      }} />
                    </div>
                  ))}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
