'use client';

import { useState, useEffect, useRef } from 'react';
import { QueryInterface } from '@/components/QueryInterface';
import { ResultsDisplay } from '@/components/ResultsDisplay';
import { getOrCreateSessionId, fetchSessionContext, clearSession, type ConversationContext } from '@/lib/session';

const parseErrorMessage = (msg: string) => {
  let mainMsg = msg;
  let suggestion: string | null = null;
  let suggestionType: 'did-you-mean' | 'try-searching' = 'did-you-mean';

  const didYouMeanIndex = msg.indexOf("Did you mean: ");
  const trySearchingIndex = msg.indexOf("Try searching for: ");

  if (didYouMeanIndex !== -1) {
    mainMsg = msg.substring(0, didYouMeanIndex).trim();
    const rawSuggestion = msg.substring(didYouMeanIndex + "Did you mean: ".length).trim();
    suggestion = rawSuggestion.replace(/^['"]|['"]\??$/g, '').trim();
    suggestionType = 'did-you-mean';
  } else if (trySearchingIndex !== -1) {
    mainMsg = msg.substring(0, trySearchingIndex).trim();
    const rawSuggestion = msg.substring(trySearchingIndex + "Try searching for: ".length).trim();
    suggestion = rawSuggestion;
    suggestionType = 'try-searching';
  }

  return { mainMsg, suggestion, suggestionType };
};

const parseTrySearchingList = (sug: string) => {
  return sug.split(',').map(item => {
    let cleaned = item.trim().replace(/^['"]|['"]\??$/g, '');
    if (cleaned.startsWith("or ")) {
      cleaned = cleaned.substring(3).trim();
    }
    if (cleaned.endsWith('.')) {
      cleaned = cleaned.slice(0, -1);
    }
    return cleaned.replace(/^['"]|['"]$/g, '').trim();
  }).filter(x => x.length > 0);
};

const detectMetricsInQuery = (query: string, metrics: string[]): string[] => {
  if (!query) return [];
  const qLower = query.toLowerCase();
  const detected: string[] = [];

  metrics.forEach(m => {
    const cleanMetric = m.toLowerCase().replace(/_/g, ' ');
    if (qLower.includes(m.toLowerCase()) || qLower.includes(cleanMetric)) {
      if (!detected.includes(m)) {
        detected.push(m);
      }
      return;
    }
    const words = cleanMetric.split(' ').filter(w => w.length >= 4);
    if (words.length > 0) {
      const matchesKeyword = words.some(w => {
        const regex = new RegExp(`\\b${w}\\b`, 'i');
        return regex.test(qLower);
      });
      if (matchesKeyword && !detected.includes(m)) {
        detected.push(m);
      }
    }
  });

  return detected;
};

const detectStateInQuery = (query: string, regions: string[]): string | null => {
  if (!query) return null;
  const qLower = query.toLowerCase();
  for (const r of regions) {
    if (qLower.includes(r.toLowerCase())) {
      return r;
    }
  }
  return null;
};

const detectYearInQuery = (query: string): string | null => {
  if (!query) return null;
  const match = query.match(/\b(202[0-6])\b/);
  return match ? match[1] : null;
};

let cleanFetch: typeof fetch | null = null;
function getCleanFetch(): typeof fetch {
  if (cleanFetch) return cleanFetch;
  if (typeof window === 'undefined') return fetch;
  try {
    const iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    document.body.appendChild(iframe);
    cleanFetch = iframe.contentWindow?.fetch || window.fetch;
  } catch (e) {
    cleanFetch = window.fetch;
  }
  return cleanFetch || window.fetch;
}


export default function Home() {
  const [results, setResults] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recentQueries, setRecentQueries] = useState<{query: string, result: any}[]>([]);
  const [devMode, setDevMode] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const [forceLLM, setForceLLM] = useState(false);
  const [iqpEnabled, setIqpEnabled] = useState(true);
  const [cacheCatalog, setCacheCatalog] = useState<any[]>([]);
  const [lineageNodes, setLineageNodes] = useState<any[]>([]);

  // Metadata props
  const [metadataMetrics, setMetadataMetrics] = useState<string[]>([]);
  const [metadataDepts, setMetadataDepts] = useState<string[]>([]);
  const [metadataRegions, setMetadataRegions] = useState<string[]>([]);

  // Session & conversation state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [conversationContext, setConversationContext] = useState<ConversationContext | null>(null);

  // Query override state
  const [queryOverride, setQueryOverride] = useState<string | null>(null);
  const [lastSubmittedQuery, setLastSubmittedQuery] = useState('');

  // Live KPIs shown in the sidebar as the user types
  const [liveKpis, setLiveKpis] = useState<Record<string, number> | null>(null);
  const [liveQuery, setLiveQuery] = useState('');
  const liveDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Prevents live-debounce from re-fetching when loading a cached recent result
  const skipNextLiveQueryRef = useRef(false);

  // Related metrics that appear after 2s of no typing
  const [relatedMetrics, setRelatedMetrics] = useState<string[]>([]);
  const relatedMetricsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Suppress uncaught AbortErrors in Next.js Dev Overlay
  useEffect(() => {
    const handleRejection = (e: PromiseRejectionEvent) => {
      const msg = e.reason?.message || '';
      const name = e.reason?.name || '';
      if (name === 'AbortError' || msg.includes('aborted') || msg.includes('abort') || name.includes('Abort')) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    const handleError = (e: ErrorEvent) => {
      const msg = e.message || '';
      const name = e.error?.name || '';
      if (name === 'AbortError' || msg.includes('aborted') || msg.includes('abort') || name.includes('Abort')) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener('unhandledrejection', handleRejection, true);
    window.addEventListener('error', handleError, true);
    return () => {
      window.removeEventListener('unhandledrejection', handleRejection, true);
      window.removeEventListener('error', handleError, true);
    };
  }, []);


  // Initialize session on mount — load from localStorage or create new
  useEffect(() => {
    getOrCreateSessionId().then(async (sid) => {
      setSessionId(sid);
      // Rehydrate conversation context (survives page refresh)
      const ctx = await fetchSessionContext(sid);
      if (ctx) {
        if (ctx.has_context) {
          setConversationContext(ctx);
        }
        if (ctx.snapshot) {
          setResults(ctx.snapshot);
          if (ctx.snapshot.kpis) {
            setLiveKpis(ctx.snapshot.kpis);
          }
          if (ctx.snapshot.conversation_context?.last_query) {
            setLastSubmittedQuery(ctx.snapshot.conversation_context.last_query);
            setLiveQuery(ctx.snapshot.conversation_context.last_query);
            setQueryOverride(ctx.snapshot.conversation_context.last_query);
          }
        }
      }
    });
  }, []);

  // Load metadata on mount
  useEffect(() => {
    fetch('/api/metadata')
      .then(r => r.json())
      .then(data => {
        if (data.metrics && data.categoricals) {
          setMetadataMetrics(data.metrics);
          setMetadataDepts(data.categoricals.project_type || data.categoricals.department || []);
          setMetadataRegions(data.categoricals.state || data.categoricals.location || data.categoricals.region || []);
        }
      })
      .catch(() => {});
  }, []);

  // Fetch active cache catalog and session lineage when Dev Mode is active
  useEffect(() => {
    if (devMode && sessionId) {
      // Fetch active cache tables
      fetch(`/api/session/${sessionId}/cache`)
        .then(res => res.json())
        .then(data => {
          if (data.caches) {
            setCacheCatalog(data.caches);
          }
        })
        .catch(err => console.error("Error fetching cache catalog:", err));

      // Fetch session lineage
      fetch(`/api/session/${sessionId}/lineage`)
        .then(res => res.json())
        .then(data => {
          if (data.lineage) {
            setLineageNodes(data.lineage);
          }
        })
        .catch(err => console.error("Error fetching lineage nodes:", err));
    }
  }, [devMode, sessionId, results]);

  // After 2 seconds of no typing, populate relatedMetrics with non-detected metrics
  useEffect(() => {
    // Clear related metrics immediately when typing resumes
    setRelatedMetrics([]);
    if (relatedMetricsTimerRef.current) clearTimeout(relatedMetricsTimerRef.current);

    if (!liveQuery.trim() || metadataMetrics.length === 0) return;

    relatedMetricsTimerRef.current = setTimeout(() => {
      const detected = detectMetricsInQuery(liveQuery, metadataMetrics);
      const related = metadataMetrics
        .filter(m => !detected.includes(m))
        .slice(0, 3);
      setRelatedMetrics(related);
    }, 2000);

    return () => {
      if (relatedMetricsTimerRef.current) clearTimeout(relatedMetricsTimerRef.current);
    };
  }, [liveQuery, metadataMetrics]);

  // Load recents from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('alphabot_recents');
    if (saved) {
      try { setRecentQueries(JSON.parse(saved)); } catch {}
    }
  }, []);

  // Whenever the result changes, sync KPIs from the latest full result
  useEffect(() => {
    if (results?.kpis) setLiveKpis(results.kpis);
  }, [results]);

  // Live Search: debounced 800ms — only fires after user genuinely pauses
  // (avoids firing expensive Ollama calls on every single keystroke)
  const handleLiveTyping = (q: string) => {
    setLiveQuery(q);
    setError(null); // Clear errors immediately as user types
    if (liveDebounceRef.current) clearTimeout(liveDebounceRef.current);
    if (recentTimerRef.current) {
      clearTimeout(recentTimerRef.current);
      recentTimerRef.current = null;
    }
    
    const trimmed = q.trim();
    if (!trimmed) {
      // Clear results and live KPIs immediately if query is cleared
      setResults(null);
      setLiveKpis(null);
      return;
    }

    // If a recent result was just loaded from cache, skip the full query round-trip
    if (skipNextLiveQueryRef.current) {
      skipNextLiveQueryRef.current = false;
      return;
    }
    
    // Original live execution mode: Debounce 800ms -> Full Query execution
    liveDebounceRef.current = setTimeout(async () => {
      handleQuery(trimmed);
    }, 800);
  };

  const handleQuery = async (query: string) => {
    // Prevent double execution from active typing debounces
    if (liveDebounceRef.current) {
      clearTimeout(liveDebounceRef.current);
      liveDebounceRef.current = null;
    }

    setIsLoading(true);
    setError(null);
    setLastSubmittedQuery(query);
    setQueryOverride(null);

    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          raw_query: query, 
          blueprint: null,
          force_llm: forceLLM,
          disable_iqp: !iqpEnabled,
          session_id: sessionId,   // ← always send session ID
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Query failed');
      }

      const data = await response.json();
      setResults(data);
      if (data.kpis) setLiveKpis(data.kpis);
      // Update conversation context from the response
      if (data.conversation_context) {
        setConversationContext(data.conversation_context);
      }


      // Save to recent queries after 5 seconds on screen
      if (recentTimerRef.current) {
        clearTimeout(recentTimerRef.current);
      }
      recentTimerRef.current = setTimeout(() => {
        setRecentQueries(prev => {
          const filtered = prev.filter(item => item.query.toLowerCase() !== query.toLowerCase());
          const updated = [{ query, result: data }, ...filtered].slice(0, 5);
          localStorage.setItem('alphabot_recents', JSON.stringify(updated));
          return updated;
        });
      }, 5000);

    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const loadRecent = (item: {query: string, result: any}) => {
    // Immediately display cached result — no HTTP call needed
    skipNextLiveQueryRef.current = true;
    if (liveDebounceRef.current) {
      clearTimeout(liveDebounceRef.current);
      liveDebounceRef.current = null;
    }
    setResults(item.result);
    setLastSubmittedQuery(item.query);
    setLiveQuery(item.query);
    setQueryOverride(item.query);
    if (item.result?.kpis) setLiveKpis(item.result.kpis);
    if (item.result?.conversation_context) setConversationContext(item.result.conversation_context);
    setError(null);
  };

  const handleFollowUpClick = (q: string) => {
    setQueryOverride(q);
    setLiveQuery(q);
    handleQuery(q);
  };

  const handleClearSession = async () => {
    if (sessionId) {
      await clearSession(sessionId);
      // Re-create a fresh session
      const { getOrCreateSessionId: mkSession } = await import('@/lib/session');
      const newSid = await mkSession();
      setSessionId(newSid);
    }
    setConversationContext(null);
  };

  return (
    <div className={darkMode ? 'dark' : ''}>
      <div className="h-screen flex bg-gray-50 dark:bg-slate-950 overflow-hidden text-slate-800 dark:text-slate-100 transition-colors duration-200">

        {/* Thin icon sidebar */}
        <aside className="w-[72px] bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-800 flex flex-col items-center py-4 flex-shrink-0 z-20 shadow-sm transition-colors duration-200">
          <div className="w-10 h-10 mb-8 flex items-center justify-center">
            <svg viewBox="0 0 40 40" className="w-8 h-8" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M20 5L10 30h5l2.5-6.25h5L25 30h5L20 5z" fill="#4F46E5"/>
              <path d="M15 25L20 12.5 25 25h-10z" fill="#10B981" opacity="0.8"/>
            </svg>
          </div>

          <div className="flex-1 flex flex-col items-center gap-6 w-full">
            <button className="w-10 h-10 bg-blue-100 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 rounded-lg flex items-center justify-center">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
                <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
              </svg>
            </button>
          </div>

          <div className="flex flex-col items-center gap-4 w-full mt-auto">
            <button className="w-10 h-10 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-850 rounded-lg flex items-center justify-center transition-colors">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
              </svg>
            </button>
            <div className="w-8 h-8 rounded-full bg-gray-500 text-white flex items-center justify-center font-semibold text-sm">N</div>
          </div>
        </aside>

        {/* Main Container */}
        <div className="flex-1 flex flex-col min-w-0">

          {/* Header */}
          <header className="bg-white dark:bg-slate-900 border-b border-gray-200 dark:border-slate-800 px-6 py-4 flex-shrink-0 z-10 flex items-center justify-between gap-4 transition-colors duration-200">
            <div className="flex items-center gap-4">
              <h1 className="text-xl font-bold text-gray-900 dark:text-slate-50 tracking-tight">Alphabot Analytics</h1>
              <div className="px-3 py-1 bg-green-50 dark:bg-green-950/20 border border-green-100 dark:border-green-900/30 rounded-full flex items-center gap-2">
                <div className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse"/>
                <span className="text-xs font-semibold text-green-700 dark:text-green-400">8 Plants Connected</span>
              </div>
            </div>

            <div className="flex items-center gap-6">
              {/* Dev Mode Toggle */}
              <div className="flex items-center gap-2.5">
                <span className="text-xs font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider">Dev Mode</span>
                <button
                  onClick={() => setDevMode(!devMode)}
                  className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${devMode ? 'bg-blue-600' : 'bg-gray-200 dark:bg-slate-800'}`}
                >
                  <span className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${devMode ? 'translate-x-5' : 'translate-x-0'}`}/>
                </button>
              </div>
            </div>
          </header>

          {/* Developer Mode Panel */}
          {devMode && (
            <div className="bg-purple-50 dark:bg-purple-950/20 border-b border-purple-200 dark:border-purple-900/30 px-6 py-3 transition-colors duration-200 max-h-[35vh] overflow-y-auto">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-6 flex-wrap">

                  {/* Engine mode radios */}
                  <div>
                    <h3 className="text-xs font-semibold text-purple-900 dark:text-purple-300 uppercase tracking-wider mb-2">Engine Mode</h3>
                    <div className="flex items-center gap-4">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          checked={!forceLLM}
                          onChange={() => setForceLLM(false)}
                          className="w-4 h-4 text-purple-600"
                        />
                        <span className="text-sm text-gray-700 dark:text-slate-300">
                          <span className="font-semibold">Hybrid</span>
                          <span className="text-gray-400 dark:text-slate-500 text-xs ml-1">(det. + LLM fallback)</span>
                        </span>
                      </label>
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="radio"
                          checked={forceLLM}
                          onChange={() => setForceLLM(true)}
                          className="w-4 h-4 text-purple-600"
                        />
                        <span className="text-sm text-gray-700 dark:text-slate-300">
                          <span className="font-semibold">LLM-Only</span>
                          <span className="text-gray-400 dark:text-slate-500 text-xs ml-1">(always Ollama)</span>
                        </span>
                      </label>
                    </div>
                  </div>

                  {/* Divider */}
                  <div className="h-8 w-px bg-purple-200 dark:bg-purple-800 hidden sm:block" />

                  {/* IQP toggle */}
                  <div>
                    <h3 className="text-xs font-semibold text-purple-900 dark:text-purple-300 uppercase tracking-wider mb-2">IQP Cache</h3>
                    <button
                      onClick={() => setIqpEnabled(v => !v)}
                      title={iqpEnabled ? 'IQP enabled — click to disable' : 'IQP disabled — click to enable'}
                      className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all duration-200 select-none ${
                        iqpEnabled
                          ? 'bg-emerald-100 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-700 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-200 dark:hover:bg-emerald-900/50'
                          : 'bg-gray-100 dark:bg-slate-800 border-gray-300 dark:border-slate-600 text-gray-500 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-700'
                      }`}
                    >
                      {/* Toggle track */}
                      <span className={`relative inline-flex h-4 w-7 flex-shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ${
                        iqpEnabled ? 'bg-emerald-500' : 'bg-gray-300 dark:bg-slate-600'
                      }`}>
                        <span className={`pointer-events-none inline-block h-3 w-3 transform rounded-full bg-white shadow transition duration-200 ${
                          iqpEnabled ? 'translate-x-3' : 'translate-x-0'
                        }`} />
                      </span>
                      <span>{iqpEnabled ? '⚡ IQP ON' : '○ IQP OFF'}</span>
                    </button>
                  </div>

                  {/* Live IQP route badge from last result */}
                  {results?.metadata?.iqp && (
                    <div className="hidden sm:flex flex-col gap-0.5">
                      <h3 className="text-xs font-semibold text-purple-900 dark:text-purple-300 uppercase tracking-wider">Last Route</h3>
                      <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold ${
                        results.metadata.iqp.cache_hit
                          ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                      }`}>
                        {results.metadata.iqp.cache_hit
                          ? '⚡ DuckDB Local'
                          : '🌐 Federated SQLite'}
                      </span>
                    </div>
                  )}
                </div>

                {/* Last query timing */}
                {results?.metadata && (
                  <div className="text-right flex-shrink-0">
                    <div className="text-xs text-gray-500 dark:text-slate-400 mb-1">Last Query</div>
                    <div className="text-sm font-semibold text-purple-900 dark:text-purple-200">
                      {results.metadata.engine_mode === 'llm_only' && '🤖 LLM Only'}
                      {results.metadata.engine_mode === 'hybrid_deterministic' && '⚡ Hybrid (Deterministic)'}
                      {results.metadata.engine_mode === 'hybrid_llm' && '🔀 Hybrid (LLM Fallback)'}
                      {!results.metadata.engine_mode && (
                        results.metadata.parsed_deterministically ? '⚡ Hybrid (Deterministic)' : '🔀 Hybrid (LLM)'
                      )}
                    </div>
                    <div className="text-xs text-gray-600 dark:text-slate-400 mt-1">
                      {Math.round(results.metadata.backend_ms || 0)}ms
                    </div>
                  </div>
                )}
              </div>


            </div>
          )}

          {/* Main Content */}
          <main className="flex-1 flex overflow-hidden">

            {/* Left panel — Query interface */}
            <div className="w-[360px] bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-800 flex flex-col flex-shrink-0 shadow-[2px_0_8px_-4px_rgba(0,0,0,0.05)] z-0 transition-colors duration-200">
              <div className="flex-1 overflow-y-auto p-6">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-slate-100 mb-4">Ask a Question</h2>
                <QueryInterface
                  onSubmit={handleQuery}
                  isLoading={isLoading}
                  recentQueries={recentQueries}
                  onSelectRecent={loadRecent}
                  liveKpis={liveKpis}
                  onQueryChange={handleLiveTyping}
                  results={results}
                  conversationContext={conversationContext}
                  onClearSession={handleClearSession}
                  queryOverride={queryOverride}
                  onClearOverride={() => setQueryOverride(null)}
                  metadataMetrics={metadataMetrics}
                  metadataDepts={metadataDepts}
                  metadataRegions={metadataRegions}
                />
              </div>
            </div>

            {/* Right panel — Results & Errors */}
            <div className="flex-1 overflow-y-auto bg-gray-50/50 dark:bg-slate-950/40 transition-colors duration-200">
              {error ? (
                <div className="h-full flex items-center justify-center p-8 bg-gray-50/50 dark:bg-slate-950/20">
                  <div className="max-w-md w-full bg-white dark:bg-slate-900 border border-red-200 dark:border-red-950/80 shadow-lg rounded-3xl p-6 text-center">
                    <div className="w-12 h-12 bg-red-50 dark:bg-red-950/30 border border-red-100 dark:border-red-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
                      <span className="text-red-600 dark:text-red-400 text-lg font-bold">⚠</span>
                    </div>
                    <h3 className="text-sm font-bold text-slate-800 dark:text-slate-100 mb-2">Query Execution Failed</h3>
                    {(() => {
                      const { mainMsg, suggestion, suggestionType } = parseErrorMessage(error);
                      return (
                        <>
                          <p className="text-xs text-red-600 dark:text-red-400 font-semibold leading-relaxed mb-4">{mainMsg}</p>
                          {suggestion && (
                            suggestionType === 'did-you-mean' ? (
                              <div 
                                onClick={() => handleFollowUpClick(suggestion)}
                                className="mt-4 p-4 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-905 rounded-2xl text-center shadow-sm cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/60 transition-all group border-dashed"
                              >
                                <p className="text-[10px] font-bold text-blue-600 dark:text-blue-400 uppercase tracking-widest mb-1.5">Suggested Query</p>
                                <p className="text-sm font-semibold text-blue-800 dark:text-blue-200 group-hover:underline">“{suggestion}”</p>
                                <p className="text-[10px] text-blue-500 dark:text-blue-450 mt-2 font-medium">Click to run this query instantly ⚡</p>
                              </div>
                            ) : (
                              <div className="mt-4 text-center">
                                <p className="text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest mb-2.5">Try searching for</p>
                                <div className="flex flex-col gap-2">
                                  {parseTrySearchingList(suggestion).map(item => (
                                    <button
                                      key={item}
                                      type="button"
                                      onClick={() => handleFollowUpClick(item)}
                                      className="px-4 py-2 text-xs font-semibold bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl text-slate-700 dark:text-slate-200 hover:bg-blue-50 dark:hover:bg-blue-950/40 hover:text-blue-600 dark:hover:text-blue-400 hover:border-blue-200 dark:hover:border-blue-900 transition-all cursor-pointer shadow-sm text-center"
                                    >
                                      {item}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            )
                          )}
                        </>
                      );
                    })()}
                    <p className="text-[11px] text-slate-400 dark:text-slate-500 font-medium mt-4">Please refine your search query or select one of the suggested filter chips in the sidebar.</p>
                  </div>
                </div>
              ) : (results || isLoading || liveQuery.trim().length > 0) ? (
                <ResultsDisplay 
                  data={results} 
                  devMode={devMode} 
                  onFollowUpClick={handleFollowUpClick} 
                  darkMode={darkMode}
                  isLoading={isLoading || (liveQuery.trim().length > 0 && liveQuery.trim() !== lastSubmittedQuery)}
                  activeTypingMetrics={detectMetricsInQuery(liveQuery, metadataMetrics)}
                  relatedMetrics={relatedMetrics}
                  metadataMetrics={metadataMetrics}
                  detectedState={detectStateInQuery(liveQuery, metadataRegions)}
                  detectedYear={detectYearInQuery(liveQuery)}
                  cacheCatalog={cacheCatalog}
                  lineageNodes={lineageNodes}
                />
              ) : (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center max-w-md px-6">
                    <div className="w-16 h-16 bg-white dark:bg-slate-900 shadow-sm border border-gray-100 dark:border-slate-800 rounded-full flex items-center justify-center mx-auto mb-5">
                      <svg className="w-8 h-8 text-blue-500 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
                      </svg>
                    </div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-slate-50 mb-2">Ready to analyze your data</h3>
                    <p className="text-sm text-gray-500 dark:text-slate-400">Type a question in the search box and press <kbd className="px-1.5 py-0.5 bg-gray-100 dark:bg-slate-800 border border-gray-300 dark:border-slate-700 rounded text-xs font-mono text-gray-700 dark:text-slate-300">Enter</kbd> to run it instantly.</p>
                  </div>
                </div>
              )}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
