import { useRef } from 'react';
import { DataChart } from './DataChart';

const KNOWN_METRICS = [
  'capacity_mw',
  'budget_allocated',
  'budget_used',
  'budget_remaining',
  'revenue',
  'completion_percentage',
  'delay_days',
  'operating_cost',
  'marketing_spend',
  'tax_liability',
  'asset_value',
  'customer_count',
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
    const k = metricName.toLowerCase().replace(/_/g, ' ');
    if (k.includes('capacity')) {
      return `${val.toLocaleString()} MW`;
    }
    if (k.includes('percent') || k.includes('pct')) {
      return `${val.toLocaleString()}%`;
    }
    if (k.includes('delay') || k.includes('days')) {
      return `${val.toLocaleString()} Days`;
    }
    if (['headcount', 'customer_count', 'customers', 'employees', 'people'].some(keyword => k.includes(keyword))) {
      return val.toLocaleString();
    }
    const prefix = "$";
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
    
    // Extract active filters from SQL query or results
    const sqlLower = (sql_query || '').toLowerCase();
    const depts = ["solar", "wind", "hybrid", "hybrid-solar", "hybrid-wind", "sales", "digital", "marketing", "hr", "engineering", "finance", "support", "operations"];
    const regions = ["gujarat", "karnataka", "maharashtra", "rajasthan", "tamil nadu", "north", "south", "east", "west", "central"];
    const plants = ["diablo_canyon", "three_mile_island", "palo_verde", "grand_gulf", "vogtle", "hinkley_point", "kashiwazaki", "darlington"];
    
    const activeDept = depts.find(d => sqlLower.includes(`'${d}'`) || sqlLower.includes(`'${d.toLowerCase()}'`));
    const activeRegion = regions.find(r => sqlLower.includes(`'${r}'`) || sqlLower.includes(`'${r.toLowerCase()}'`));
    
    let activePlant = plants.find(p => sqlLower.includes(p));
    if (!activePlant && results.length > 0) {
      for (const row of results) {
        if (row.plant) {
          activePlant = plants.find(p => p === row.plant.toLowerCase() || p.replace('_', ' ') === row.plant.toLowerCase());
          if (activePlant) break;
        }
      }
    }
    
    const yearMatch = sqlLower.match(/\b(202[0-7])\b/);
    const activeYear = yearMatch ? yearMatch[1] : null;
    const timeLabel = activeYear ? `in ${activeYear}` : "";
    
    // Format helpers
    const formatDept = (d: string) => {
      if (d === "hr" || d === "digital") return d.toUpperCase();
      return d.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('-');
    };
    const formatRegion = (r: string) => r.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    const formatPlant = (p: string) => p.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    
    const deptLabel = activeDept ? formatDept(activeDept) : "";
    const regionLabel = activeRegion ? formatRegion(activeRegion) : "";
    const plantLabel = activePlant ? formatPlant(activePlant) : "";
    
    const questions = [];
    
    // Detect ID / Contract / Asset / Warehouse query
    const hasContractId = results[0]?.contract_ref || sqlLower.includes('contract_ref');
    const hasAssetCode = results[0]?.asset_code || sqlLower.includes('asset_code');
    const hasWarehouseId = results[0]?.warehouse_id || sqlLower.includes('warehouse_id');
    const hasProjectId = results[0]?.project_id || sqlLower.includes('project_id');
    
    if (hasContractId) {
      const contractId = results[0]?.contract_ref || "REF-001";
      const clientName = results[0]?.client_name || "Acme Corp";
      questions.push(`What is the delivery status of contract ${contractId}?`);
      questions.push(`Show project cost and completion date for contract ${contractId}`);
      questions.push(`Total project cost for ${clientName}`);
      questions.push(`Show all contracts with In Progress delivery status`);
      questions.push(`Show all contracts with Pending delivery status`);
    } else if (hasAssetCode) {
      const assetCode = results[0]?.asset_code || "AST-001";
      const plantOrFacility = results[0]?.facility_name || results[0]?.plant || "Solar Facility Alpha";
      questions.push(`What is the vendor and commission date of asset ${assetCode}?`);
      questions.push(`Show energy output by vendor for ${plantOrFacility}`);
      questions.push(`Show all assets for vendor SunPower`);
      questions.push(`Top 3 plants by energy output`);
      questions.push(`Show all assets commissioned after 2023`);
    } else if (hasWarehouseId) {
      const warehouseId = results[0]?.warehouse_id || "WH-001";
      questions.push(`What is the inventory turnover and stock value for warehouse ${warehouseId}?`);
      questions.push(`Show stock value by supplier for ${warehouseId}`);
      questions.push(`Show all warehouses with inventory turnover above 4.0`);
      questions.push(`Top 3 warehouses by stock value`);
      questions.push(`Total stock value across all warehouses`);
    } else if (hasProjectId) {
      const pid = results[0]?.project_id || "PRJ-DAR-000001";
      questions.push(`Show all details of project ${pid}`);
      questions.push(`What is the completion percentage of project ${pid}?`);
      questions.push(`What is the delay days for project ${pid}?`);
      questions.push(`Show contractor name and material status for project ${pid}`);
      questions.push(`Compare project ${pid} with other projects in the same plant`);
    } else {
      const isTrend = sqlLower.includes('strftime') || metadata?.intent === 'trend' || sqlLower.includes('group by strftime');
      const isBreakdown = sqlLower.includes('group by') && !isTrend;
      
      if (isTrend) {
        questions.push(`What was the ${cleanM} breakdown by plant ${timeLabel}`.trim());
        questions.push(`What was the ${cleanM} breakdown by state ${timeLabel}`.trim());
        questions.push(`What was the ${cleanM} breakdown by project type ${timeLabel}`.trim());
        questions.push(`Compare ${cleanM} and Budget Used ${timeLabel}`.trim());
        questions.push(`Show ${cleanM} trend for last 3 years`);
      } else if (isBreakdown) {
        const isGroupByPlant = sqlLower.includes('group by plant') || sqlLower.includes('group by comparison_group');
        const isGroupByState = sqlLower.includes('group by state') || sqlLower.includes('group by location');
        
        if (isGroupByPlant) {
          questions.push(`Show ${cleanM} trend by plant ${timeLabel}`.trim());
          questions.push(`Compare ${cleanM} of top performing plants`);
          questions.push(`What was the capacity MW breakdown by plant ${timeLabel}`.trim());
          questions.push(`What was the budget allocated by plant ${timeLabel}`.trim());
          questions.push(`Show completion percentage by plant ${timeLabel}`.trim());
        } else if (isGroupByState) {
          questions.push(`Show ${cleanM} trend by state ${timeLabel}`.trim());
          questions.push(`Compare ${cleanM} in Gujarat and Rajasthan ${timeLabel}`.trim());
          questions.push(`What was the budget allocated by state ${timeLabel}`.trim());
          questions.push(`Show delay days breakdown by state ${timeLabel}`.trim());
          questions.push(`Top performing plants in Gujarat`);
        } else {
          questions.push(`Show ${cleanM} trend by project type ${timeLabel}`.trim());
          questions.push(`Compare ${cleanM} of Solar and Wind ${timeLabel}`.trim());
          questions.push(`What was the completion percentage by project type ${timeLabel}`.trim());
          questions.push(`What was the delay days breakdown by project type ${timeLabel}`.trim());
          questions.push(`Compare budget allocated by project type ${timeLabel}`.trim());
        }
      } else {
        if (activeDept && activeRegion) {
          questions.push(`Compare ${deptLabel} ${cleanM} in ${regionLabel} and South`);
          questions.push(`Show ${deptLabel} ${cleanM} trend in ${regionLabel} over time`);
          questions.push(`Compare ${deptLabel} and Digital ${cleanM} in ${regionLabel}`);
          questions.push(`Show ${deptLabel} ${cleanM} breakdown by plant in ${regionLabel}`);
          questions.push(`Top performing plants for ${deptLabel} in ${regionLabel}`);
        } else if (activePlant) {
          questions.push(`Show ${cleanM} trend for ${plantLabel}`);
          questions.push(`What was the ${cleanM} breakdown by project type for ${plantLabel}?`);
          questions.push(`Compare ${plantLabel} and Darlington ${cleanM}`);
          questions.push(`Show all metrics for ${plantLabel}`);
          questions.push(`What was the completion percentage for ${plantLabel}?`);
        } else if (activeRegion) {
          questions.push(`Show ${cleanM} trend in ${regionLabel}`);
          questions.push(`What was the ${cleanM} breakdown by project type in ${regionLabel}?`);
          questions.push(`Compare ${cleanM} in ${regionLabel} and Rajasthan`);
          questions.push(`Show ${cleanM} breakdown by plant in ${regionLabel}`);
          questions.push(`Top 3 performing plants in ${regionLabel}`);
        } else if (activeDept) {
          questions.push(`Show ${deptLabel} ${cleanM} trend over time`);
          questions.push(`What was the ${deptLabel} ${cleanM} breakdown by state?`);
          questions.push(`What was the ${deptLabel} ${cleanM} breakdown by plant?`);
          questions.push(`Compare ${deptLabel} and Wind ${cleanM}`);
          questions.push(`Top 3 plants by ${deptLabel} ${cleanM}`);
        } else {
          questions.push(`Show ${cleanM} trend over time`);
          questions.push(`What was the ${cleanM} breakdown by plant ${timeLabel}`.trim());
          questions.push(`What was the ${cleanM} breakdown by state ${timeLabel}`.trim());
          questions.push(`What was the ${cleanM} breakdown by project type ${timeLabel}`.trim());
          questions.push(`Compare ${cleanM} in 2025 and 2026`);
        }
      }
    }
    
    return questions.slice(0, 5);
  };

  const formatKPIValue = (val: any, key: string) => {
    if (val == null) return "0";
    const k = key.toLowerCase();
    if (k.includes('capacity')) {
      return `${val.toLocaleString()} MW`;
    }
    if (k.includes('percent') || k.includes('pct')) {
      return `${val.toLocaleString()}%`;
    }
    if (k.includes('delay') || k.includes('days')) {
      return `${val.toLocaleString()} Days`;
    }
    if (k.includes('headcount') || k.includes('count')) {
      return val.toLocaleString();
    }
    // Currency formatting
    const prefix = "$";
    if (val >= 1000000) return `${prefix}${(val / 1000000).toFixed(1)}M`;
    if (val >= 1000) return `${prefix}${(val / 1000).toFixed(1)}K`;
    return prefix + val.toLocaleString();
  };

  return (
    <div className="p-6 space-y-6">
      {/* 1. Contextual KPIs Bar */}
      {kpis && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {Object.entries(kpis).map(([key, val]) => {
            const name = key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
            const formattedVal = formatKPIValue(val, key);
            return (
              <div key={key} className="bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800/80 shadow-sm rounded-2xl p-5 flex flex-col justify-between transition-all hover:shadow-md">
                <div>
                  <p className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2">{name}</p>
                  <p className="text-3xl font-extrabold text-gray-900 dark:text-slate-50 tracking-tight">{formattedVal}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

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

          {sql_query && (
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
          )}
        </div>
      )}
    </div>
  );
}
