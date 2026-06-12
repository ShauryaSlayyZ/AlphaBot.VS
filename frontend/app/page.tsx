'use client';

import { useState, useEffect, useRef } from 'react';
import { QueryInterface } from '@/components/QueryInterface';
import { ResultsDisplay } from '@/components/ResultsDisplay';

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

export default function Home() {
  const [results, setResults] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recentQueries, setRecentQueries] = useState<{query: string, result: any}[]>([]);
  const [devMode, setDevMode] = useState(false);
  const [darkMode, setDarkMode] = useState(false);

  // Live KPIs shown in the sidebar as the user types
  const [liveKpis, setLiveKpis] = useState<{
    revenue?: number; profit?: number; expenses?: number; headcount?: number;
  } | null>(null);
  const [liveQuery, setLiveQuery] = useState('');
  const liveDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Live Search: debounced 150ms after user stops typing
  // Executes full analysis and updates all dashboard components in real time
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
    
    liveDebounceRef.current = setTimeout(async () => {
      handleQuery(trimmed);
    }, 150);
  };

  const handleQuery = async (query: string) => {
    // Prevent double execution from active typing debounces
    if (liveDebounceRef.current) {
      clearTimeout(liveDebounceRef.current);
      liveDebounceRef.current = null;
    }
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_query: query, blueprint: null }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || 'Query failed');
      }

      const data = await response.json();
      setResults(data);
      if (data.kpis) setLiveKpis(data.kpis);

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
    setResults(item.result);
    if (item.result?.kpis) setLiveKpis(item.result.kpis);
    setError(null);
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
                />
              </div>
            </div>

            {/* Right panel — Results & Errors */}
            <div className="flex-1 overflow-y-auto bg-gray-50/50 dark:bg-slate-950/40 transition-colors duration-200">
              {isLoading ? (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center">
                    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-500 dark:border-blue-400 mx-auto mb-4"/>
                    <p className="text-sm font-semibold text-gray-600 dark:text-slate-400">Analyzing data…</p>
                  </div>
                </div>
              ) : error ? (
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
                                onClick={() => { setLiveQuery(suggestion); handleQuery(suggestion); }}
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
                                      onClick={() => { setLiveQuery(item); handleQuery(item); }}
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
              ) : results ? (
                <ResultsDisplay data={results} devMode={devMode} onFollowUpClick={handleQuery} darkMode={darkMode}/>
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
