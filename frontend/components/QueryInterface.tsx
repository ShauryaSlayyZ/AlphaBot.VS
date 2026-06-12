import { useState, useRef, useEffect, useCallback } from 'react';

interface QueryInterfaceProps {
  onSubmit: (query: string) => void;
  isLoading: boolean;
  recentQueries?: {query: string, result: any}[];
  onSelectRecent?: (item: {query: string, result: any}) => void;
  liveKpis?: { revenue?: number; profit?: number; expenses?: number; headcount?: number } | null;
  onQueryChange?: (q: string) => void;
  results?: any;
}

interface CategorizedSuggestions {
  metrics: string[];
  analysis: string[];
  comparisons: string[];
}

interface Preview {
  intent: string;
  metric: string;
  dimension: string;
}

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

export function QueryInterface({ onSubmit, isLoading, recentQueries, onSelectRecent, liveKpis, onQueryChange, results }: QueryInterfaceProps) {
  const [query, setQuery] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [categorizedSuggestions, setCategorizedSuggestions] = useState<CategorizedSuggestions>({
    metrics: [], analysis: [], comparisons: []
  });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [lastSubmitted, setLastSubmitted] = useState('');
  const [isFocused, setIsFocused] = useState(false);

  const getFollowUpQuestions = () => {
    if (!results || !results.results) return [];
    const detectedMetrics = extractMetrics(results.sql_query, results.results);
    const m = detectedMetrics[0] || "revenue";
    const cleanM = m.replace(/_/g, ' ');
    const capM = cleanM.charAt(0).toUpperCase() + cleanM.slice(1);
    
    // Extract active filters from SQL query
    const sqlLower = (results.sql_query || '').toLowerCase();
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

  const [metrics, setMetrics] = useState<string[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);
  const suggestionListRef = useRef<HTMLDivElement>(null);
  const tagsRef = useRef<HTMLDivElement>(null);

  const scrollToTags = () => {
    tagsRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  // Load metadata
  useEffect(() => {
    fetch('/api/metadata')
      .then(r => r.json())
      .then(data => {
        if (data.metrics && data.categoricals) {
          setMetrics(data.metrics.map((x: string) => x.replace(/_/g, ' ')));
          setDepartments(data.categoricals.department || []);
          setRegions(data.categoricals.region || []);
        }
      })
      .catch(() => {});
  }, []);

  // Live suggestions as user types (50ms debounce)
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`/api/suggest?q=${encodeURIComponent(query)}`);
        if (res.ok) {
          const data = await res.json();
          setCategorizedSuggestions(data.suggestions);
          setPreview(data.preview);
          if (isFocused || document.activeElement === inputRef.current) {
            setShowSuggestions(true);
          }
        }
      } catch {}
    }, 50);
    return () => clearTimeout(t);
  }, [query, isFocused]);

  const runQuery = useCallback((q: string) => {
    const trimmed = q.trim();
    if (!trimmed || trimmed === lastSubmitted || isLoading) return;
    setLastSubmitted(trimmed);
    setShowSuggestions(false);
    onSubmit(trimmed);
  }, [lastSubmitted, isLoading, onSubmit]);

  const handleTextChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    setSelectedIndex(-1);
    setShowSuggestions(true);
    if (onQueryChange) onQueryChange(val);
  };

  const handleTagClick = (tag: string) => {
    const next = (query + ' ' + tag).trim();
    setQuery(next);
    setSelectedIndex(-1);
    setShowSuggestions(true);
    if (onQueryChange) onQueryChange(next);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const flatSuggestions = [
    ...categorizedSuggestions.metrics,
    ...categorizedSuggestions.analysis,
    ...categorizedSuggestions.comparisons,
  ];

  const getFlatIndex = (cat: 'metrics' | 'analysis' | 'comparisons', idx: number) => {
    if (cat === 'metrics') return idx;
    if (cat === 'analysis') return categorizedSuggestions.metrics.length + idx;
    return categorizedSuggestions.metrics.length + categorizedSuggestions.analysis.length + idx;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(p => (p < flatSuggestions.length - 1 ? p + 1 : p));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(p => (p > 0 ? p - 1 : -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selectedIndex >= 0) {
        const s = flatSuggestions[selectedIndex];
        setQuery(s);
        setSelectedIndex(-1);
        runQuery(s);
      } else {
        runQuery(query);
      }
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
    }
  };

  const handleSuggestionClick = (s: string) => {
    setQuery(s);
    setSelectedIndex(-1);
    runQuery(s);
  };

  // Scroll active suggestion into view
  useEffect(() => {
    if (selectedIndex >= 0 && suggestionListRef.current) {
      const items = suggestionListRef.current.querySelectorAll('li');
      (items[selectedIndex] as HTMLElement)?.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex]);

  // Hide on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (inputRef.current?.contains(e.target as Node)) return;
      if (suggestionListRef.current?.contains(e.target as Node)) return;
      setTimeout(() => setShowSuggestions(false), 150);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div>
      {/* Search input */}
      <div className="relative mb-3">
        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
          {isLoading
            ? <svg className="animate-spin h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
            : <svg className="h-4 w-4 text-blue-500 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
              </svg>
          }
        </div>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleTextChange}
          onFocus={() => {
            setIsFocused(true);
            setShowSuggestions(true);
          }}
          onBlur={() => {
            setIsFocused(false);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your data…"
          className="w-full pl-10 pr-4 py-2.5 text-sm bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 hover:border-blue-300 dark:hover:border-blue-700 text-slate-850 dark:text-slate-100 placeholder-slate-450 rounded-2xl focus:outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-600 focus:border-transparent transition-all shadow-sm font-medium"
        />

        {/* Suggestions dropdown */}
        {showSuggestions && flatSuggestions.length > 0 && (
          <div
            ref={suggestionListRef}
            className="absolute z-20 w-full bg-white dark:bg-slate-900 border border-gray-100 dark:border-slate-800 rounded-2xl shadow-2xl mt-2 max-h-72 overflow-y-auto p-2 flex flex-col gap-1 transition-colors duration-200"
          >
            {(['metrics', 'analysis', 'comparisons'] as const).map(cat => {
              const items = categorizedSuggestions[cat];
              if (!items.length) return null;
              const label = cat === 'metrics' ? 'Core Queries' : cat === 'analysis' ? 'Suggested Queries' : 'Comparisons';
              return (
                <div key={cat}>
                  <div className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider px-3 py-1">{label}</div>
                  <ul>
                    {items.map((s, idx) => {
                      const fi = getFlatIndex(cat, idx);
                      return (
                        <li
                          key={`${cat}-${idx}`}
                          className={`px-3 py-2 text-sm cursor-pointer rounded-xl font-medium transition-all ${
                            selectedIndex === fi 
                              ? 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400' 
                              : 'hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-700 dark:text-slate-200'
                          }`}
                          onMouseDown={e => { e.preventDefault(); handleSuggestionClick(s); }}
                        >
                          {s}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Real-time Copilot Thought Stream Panel */}
      {query.trim().length > 0 && (
        <div className="bg-slate-50 dark:bg-slate-850/60 border border-slate-200 dark:border-slate-800 rounded-xl p-3 mb-3 shadow-sm transition-all duration-300">
          <div className="flex items-center justify-between mb-2 pb-1 border-b border-slate-200 dark:border-slate-800">
            <div className="flex items-center gap-1.5">
              <span className="text-xs">🤖</span>
              <span className="text-xs font-bold text-slate-700 dark:text-slate-200 tracking-tight">Copilot Live Analysis</span>
            </div>
            {isLoading ? (
              <div className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-blue-500 dark:bg-blue-400 rounded-full animate-ping" />
                <span className="text-[10px] font-semibold text-blue-600 dark:text-blue-400 uppercase tracking-wider animate-pulse">Analyzing...</span>
              </div>
            ) : (
              <span className="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/30 px-1.5 py-0.5 rounded border border-emerald-200 dark:border-emerald-900/30 uppercase tracking-wider">Ready</span>
            )}
          </div>
          
          <div className="flex flex-wrap gap-1.5">
            {preview ? (
              <>
                <span className="inline-flex items-center px-2 py-0.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-650 dark:text-slate-300 border border-slate-200/60 dark:border-slate-700/60 shadow-sm">
                  Intent: <span className="font-semibold ml-1 capitalize text-slate-900 dark:text-slate-100">{preview.intent || 'Sum'}</span>
                </span>
                {preview.metric && preview.metric !== 'None' && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-650 dark:text-slate-300 border border-slate-200/60 dark:border-slate-700/60 shadow-sm">
                    Metric: <span className="font-semibold ml-1 capitalize text-slate-900 dark:text-slate-100">{preview.metric}</span>
                  </span>
                )}
                {preview.dimension && preview.dimension !== 'None' && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-650 dark:text-slate-300 border border-slate-200/60 dark:border-slate-700/60 shadow-sm">
                    By: <span className="font-semibold ml-1 capitalize text-slate-900 dark:text-slate-100">{preview.dimension}</span>
                  </span>
                )}
              </>
            ) : (
              <span className="text-xs text-slate-500 dark:text-slate-400 font-medium italic animate-pulse">Resolving schema...</span>
            )}
          </div>

          {preview && preview.metric && preview.metric !== 'None' && (
            <div className="mt-2 text-xs text-slate-750 dark:text-slate-350 font-medium bg-slate-100/50 dark:bg-slate-800/40 rounded-lg px-2 py-1 border border-slate-200/50 dark:border-slate-700/50 flex items-center justify-between shadow-sm transition-all duration-300">
              <span>Target Metric: <strong className="font-semibold text-slate-900 dark:text-slate-100">{preview.metric}</strong></span>
              <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">Column: {preview.metric.toLowerCase().replace(/ /g, '_')}</span>
            </div>
          )}
        </div>
      )}

      {/* Recent Queries */}
      {recentQueries && recentQueries.length > 0 && (
        <div className="mt-2 pt-2">
          <p className="text-xs font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2">Recent</p>
          <div className="space-y-1">
            {recentQueries.map((item, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => {
                  setQuery(item.query);
                  setLastSubmitted(item.query);
                  if (onSelectRecent) onSelectRecent(item);
                }}
                disabled={isLoading}
                className="w-full flex items-center text-left px-3 py-2 rounded-xl text-xs text-gray-600 dark:text-slate-300 hover:text-gray-900 dark:hover:text-slate-100 hover:bg-gray-50 dark:hover:bg-slate-800 border border-transparent hover:border-gray-100 dark:hover:border-slate-800 transition-all truncate"
                title={item.query}
              >
                <svg className="w-3.5 h-3.5 mr-2 text-gray-400 dark:text-slate-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span className="truncate font-medium">{item.query}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Dynamic Suggested Follow-up Questions in Left Sidebar */}
      {query.trim() !== '' && results && results.results && (
        <div className="mt-4 pt-4 border-t border-gray-100 dark:border-slate-800">
          <p className="text-xs font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2">Suggested Follow-ups</p>
          <div className="space-y-1.5">
            {getFollowUpQuestions().map((q, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => {
                  setQuery(q);
                  setSelectedIndex(-1);
                  runQuery(q);
                }}
                disabled={isLoading}
                className="w-full flex items-center justify-between text-left px-3 py-2 bg-gray-50 dark:bg-slate-850/60 hover:bg-blue-50 dark:hover:bg-blue-950/20 border border-gray-100 dark:border-slate-800 hover:border-blue-200 dark:hover:border-blue-900 rounded-xl text-xs font-semibold text-gray-700 dark:text-slate-300 hover:text-blue-700 dark:hover:text-blue-400 transition-all group"
              >
                <span className="truncate">{q}</span>
                <svg className="w-3.5 h-3.5 text-gray-400 group-hover:text-blue-500 transition-colors flex-shrink-0 ml-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Suggested Questions (empty state) */}
      {query.trim() === '' && (
        <div className="space-y-1 mt-4">
          <p className="text-xs font-semibold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2">Suggested</p>
          {[
            'Top Revenue Plants',
            'Revenue Trend',
            'Profit by Region',
            'Department Performance',
            'monthly revenue trend',
          ].map((ex, idx) => (
            <button
              key={idx}
              type="button"
              onMouseDown={e => { e.preventDefault(); setQuery(ex); runQuery(ex); }}
              disabled={isLoading}
              className="w-full text-left px-3 py-2.5 bg-gray-50 dark:bg-slate-850/60 hover:bg-blue-50 dark:hover:bg-blue-950/20 border border-gray-100 dark:border-slate-800 hover:border-blue-200 dark:hover:border-blue-900 rounded-xl text-xs font-semibold text-gray-700 dark:text-slate-300 hover:text-blue-700 dark:hover:text-blue-400 transition-all flex items-center justify-between group"
            >
              <span>{ex}</span>
              <svg className="w-3.5 h-3.5 text-gray-400 group-hover:text-blue-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
              </svg>
            </button>
          ))}
        </div>
      )}

      {/* Animated scroll indicator for metrics, departments & regions */}
      <div 
        onClick={scrollToTags}
        className="flex flex-col items-center justify-center py-4 mt-6 text-slate-400 dark:text-slate-500 cursor-pointer group hover:text-blue-500 transition-colors animate-pulse border-t border-gray-100 dark:border-slate-800"
      >
        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500 group-hover:text-blue-500 transition-colors">
          Scroll for Metrics, Departments & Regions
        </span>
        <svg className="w-3.5 h-3.5 mt-0.5 text-slate-400 dark:text-slate-500 group-hover:text-blue-500 transition-colors animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {/* Interactive tag chips */}
      <div ref={tagsRef} className="space-y-4 mt-20 pt-8 border-t border-gray-100 dark:border-slate-800">
        {[
          { title: 'Metrics', items: metrics.length > 0 ? metrics : ['Revenue', 'Profit', 'Expenses', 'Headcount'] },
          { title: 'Departments', items: departments.length > 0 ? departments : ['Sales', 'Digital', 'Marketing', 'HR'] },
          { title: 'Regions', items: regions.length > 0 ? regions : ['North', 'South', 'East', 'West', 'Central'] },
        ].map(({ title, items }) => (
          <div key={title}>
            <h3 className="text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider mb-2">{title}</h3>
            <div className="flex flex-wrap gap-1.5">
              {items.map(item => (
                <button
                  key={item}
                  type="button"
                  onClick={() => handleTagClick(item)}
                  className="px-2.5 py-1 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 hover:border-blue-300 dark:hover:border-blue-700 hover:bg-blue-50 dark:hover:bg-blue-950/20 text-gray-600 dark:text-slate-350 hover:text-blue-700 dark:hover:text-blue-400 text-xs rounded-full transition-all cursor-pointer font-medium"
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
