'use client';

import { useState, useEffect } from 'react';
import { QueryInterface } from '@/components/QueryInterface';
import { ResultsDisplay } from '@/components/ResultsDisplay';

export default function Home() {
  const [results, setResults] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recentQueries, setRecentQueries] = useState<{query: string, result: any}[]>([]);

  // Load recents from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('alphabot_recents');
    if (saved) {
      try {
        setRecentQueries(JSON.parse(saved));
      } catch (e) {
        console.error("Failed to parse recent queries", e);
      }
    }
  }, []);

  const handleQuery = async (query: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          raw_query: query,
          blueprint: null
        })
      });

      if (!response.ok) throw new Error('Query failed');
      
      const data = await response.json();
      setResults(data);

      // Save to recent queries
      setRecentQueries(prev => {
        const filtered = prev.filter(item => item.query.toLowerCase() !== query.toLowerCase());
        const updated = [{ query, result: data }, ...filtered].slice(0, 5); // Keep last 5 queries
        localStorage.setItem('alphabot_recents', JSON.stringify(updated));
        return updated;
      });

    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  const loadRecent = (item: {query: string, result: any}) => {
    setResults(item.result);
    setError(null);
  };

  return (
    <div className="h-screen flex bg-gray-50 overflow-hidden text-gray-900">
      
      {/* Thin Sidebar (New) */}
      <aside className="w-[72px] bg-white border-r border-gray-200 flex flex-col items-center py-4 flex-shrink-0 z-20 shadow-sm">
        <div className="w-10 h-10 mb-8 flex items-center justify-center">
          <svg viewBox="0 0 40 40" className="w-8 h-8" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M20 5L10 30h5l2.5-6.25h5L25 30h5L20 5z" fill="#4F46E5"/>
            <path d="M15 25L20 12.5 25 25h-10z" fill="#10B981" opacity="0.8"/>
          </svg>
        </div>
        
        <div className="flex-1 flex flex-col items-center gap-6 w-full">
          <button className="w-10 h-10 bg-blue-100 text-blue-600 rounded-lg flex items-center justify-center">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <rect x="3" y="3" width="7" height="7"></rect>
              <rect x="14" y="3" width="7" height="7"></rect>
              <rect x="14" y="14" width="7" height="7"></rect>
              <rect x="3" y="14" width="7" height="7"></rect>
            </svg>
          </button>
          
          <button className="w-10 h-10 text-gray-400 hover:text-gray-600 hover:bg-gray-50 rounded-lg flex items-center justify-center">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
            </svg>
          </button>
        </div>

        <div className="flex flex-col items-center gap-4 w-full mt-auto">
          <button className="w-10 h-10 text-gray-400 hover:text-gray-600 hover:bg-gray-50 rounded-lg flex items-center justify-center">
             <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
          <div className="w-8 h-8 rounded-full bg-gray-500 text-white flex items-center justify-center font-semibold text-sm">
            N
          </div>
        </div>
      </aside>

      {/* Main Container */}
      <div className="flex-1 flex flex-col min-w-0">
        
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex-shrink-0 z-10 flex items-center gap-4">
          <h1 className="text-xl font-bold text-gray-900 tracking-tight">Alphabot Analytics</h1>
          <div className="px-3 py-1 bg-green-50 border border-green-100 rounded-full flex items-center gap-2">
            <div className="w-1.5 h-1.5 bg-green-500 rounded-full"></div>
            <span className="text-xs font-medium text-green-700">8 Plants Connected</span>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 flex overflow-hidden">
          {/* Left Panel - Query Interface */}
          <div className="w-[360px] bg-white border-r border-gray-200 flex flex-col flex-shrink-0 shadow-[2px_0_8px_-4px_rgba(0,0,0,0.05)] z-0">
            <div className="flex-1 overflow-y-auto p-6">
              <div className="mb-2">
                <h2 className="text-sm font-semibold text-gray-900 mb-4">Ask a Question</h2>
                <QueryInterface 
                  onSubmit={handleQuery} 
                  isLoading={isLoading} 
                  recentQueries={recentQueries}
                  onSelectRecent={loadRecent}
                />
              </div>
              
              {error && (
                <div className="mb-6 p-3 bg-red-50 border border-red-200 rounded-lg">
                  <p className="text-sm font-medium text-red-800">Error</p>
                  <p className="text-sm text-red-600 mt-1">{error}</p>
                </div>
              )}
              
              <div className="mt-6">
                {/* Dynamic tags are now rendered securely within QueryInterface.tsx */}
              </div>
            </div>
          </div>

          {/* Right Panel - Results */}
          <div className="flex-1 overflow-y-auto bg-gray-50/50 p-6">
            {!results && !isLoading && (
              <div className="h-full flex items-center justify-center">
                <div className="text-center max-w-md">
                  <div className="w-16 h-16 bg-white shadow-sm border border-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                    <svg className="w-8 h-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-medium text-gray-900 mb-2">Ready to analyze your data</h3>
                  <p className="text-sm text-gray-500">Search for metrics or query across your 8 connected power plants.</p>
                </div>
              </div>
            )}
            {results && <ResultsDisplay data={results} />}
          </div>
        </main>
      </div>
    </div>
  );
}
