import { useState, FormEvent, useRef, useEffect } from 'react';

interface QueryInterfaceProps {
  onSubmit: (query: string) => void;
  isLoading: boolean;
  recentQueries?: {query: string, result: any}[];
  onSelectRecent?: (item: {query: string, result: any}) => void;
}

export function QueryInterface({ onSubmit, isLoading, recentQueries, onSelectRecent }: QueryInterfaceProps) {
  const [query, setQuery] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const [lastSubmitted, setLastSubmitted] = useState('');
  
  // Dynamic metadata from database
  const [metrics, setMetrics] = useState<string[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [plants, setPlants] = useState<string[]>([]);
  const [allKeywords, setAllKeywords] = useState<string[]>([]);

  const textareaRef = useRef<HTMLInputElement>(null);
  const suggestionListRef = useRef<HTMLUListElement>(null);
  const suggestionTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    // Fetch actual database schema/metadata to ensure suggestions are accurate
    fetch('/api/metadata')
      .then(res => res.json())
      .then(data => {
        if (data.metrics && data.categoricals) {
          const m = data.metrics.map((x: string) => x.replace(/_/g, ' '));
          const d = data.categoricals.department || [];
          const r = data.categoricals.region || [];
          const p = data.categoricals.plant || [];
          
          setMetrics(m);
          setDepartments(d);
          setRegions(r);
          setPlants(p);
          setAllKeywords([...m, ...d, ...r, ...p]);
        }
      })
      .catch(err => console.error("Failed to load metadata for autocomplete", err));
  }, []);

  // Auto-submit when user types a space and pauses
  useEffect(() => {
    const handler = setTimeout(() => {
      if (query.trim().length > 3 && query.endsWith(' ') && query !== lastSubmitted) {
        onSubmit(query);
        setLastSubmitted(query);
      }
    }, 800); // 800ms debounce
    
    return () => clearTimeout(handler);
  }, [query, lastSubmitted, onSubmit]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (query.trim() && query !== lastSubmitted) {
      onSubmit(query);
      setLastSubmitted(query);
      setShowSuggestions(false);
    }
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    
    const cursor = e.target.selectionStart || 0;
    
    if (suggestionTimeoutRef.current) clearTimeout(suggestionTimeoutRef.current);
    
    suggestionTimeoutRef.current = setTimeout(() => {
      const textBeforeCursor = val.slice(0, cursor);
      const textAfterCursor = val.slice(cursor);
      const words = textBeforeCursor.split(/\s+/);
      const lastWord = words[words.length - 1].toLowerCase();

      let newSuggestions: string[] = [];

      if (lastWord.length > 0) {
        // Typing a word: suggest completions from DB
        const matches = allKeywords.filter(k => k.startsWith(lastWord) && k !== lastWord);
        
        // Also match structural query words
        const structural = ['what is', 'show me', 'breakdown', 'total', 'average'].filter(k => k.startsWith(lastWord));
        
        if (matches.length > 0 || structural.length > 0) {
          words.pop(); // remove partial word
          const prefix = words.length > 0 ? words.join(' ') + ' ' : '';
          newSuggestions = [...matches, ...structural].map(m => prefix + m + ' ' + textAfterCursor);
        }
      } else {
        // Trailing space - suggest next logical words to form a correct query
        const prevWord = words.length > 1 ? words[words.length - 2].toLowerCase() : '';
        let nextWords: string[] = [];
        
        if (prevWord === 'in' || prevWord === 'for') {
          nextWords = [...departments, ...regions, ...plants, '2023', '2024', '2025', '2026'];
        } else if (prevWord === 'by') {
          nextWords = ['department', 'region', 'plant', 'year'];
        } else if (prevWord === 'of') {
          nextWords = [...metrics, ...departments];
        } else if (metrics.includes(prevWord)) {
          nextWords = ['in', 'by', 'for'];
        } else if (departments.includes(prevWord) || regions.includes(prevWord) || plants.includes(prevWord)) {
          nextWords = ['in', 'by year'];
        } else if (prevWord === 'the') {
          nextWords = ['breakdown of', 'total', ...metrics];
        } else if (prevWord === 'is' || prevWord === 'me') {
          nextWords = ['the total', 'the breakdown of'];
        } else if (!prevWord) {
          nextWords = ['what is the', 'show me the', 'breakdown of', ...metrics];
        }
        
        if (nextWords.length > 0) {
          newSuggestions = nextWords.map(w => textBeforeCursor + w + ' ' + textAfterCursor);
        }
      }

      if (newSuggestions.length > 0) {
        // Deduplicate, trim and limit
        newSuggestions = Array.from(new Set(newSuggestions.map(s => s.trim().replace(/\s+/g, ' ')))).slice(0, 8);
        setSuggestions(newSuggestions);
        setShowSuggestions(true);
        setSelectedIndex(-1);
      } else {
        setShowSuggestions(false);
      }
    }, 50); // Small 50ms debounce
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!showSuggestions || suggestions.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev < suggestions.length - 1 ? prev + 1 : prev));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev > 0 ? prev - 1 : -1));
    } else if (e.key === 'Enter') {
      if (selectedIndex >= 0) {
        e.preventDefault();
        handleSuggestionClick(suggestions[selectedIndex]);
      } else {
        e.preventDefault();
        if (query.trim() && query !== lastSubmitted) {
          onSubmit(query);
          setLastSubmitted(query);
          setShowSuggestions(false);
        }
      }
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setQuery(suggestion + ' ');
    setShowSuggestions(false);
    
    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        const len = suggestion.length + 1;
        textareaRef.current.setSelectionRange(len, len);
      }
    }, 0);
  };

  // Scroll active item into view
  useEffect(() => {
    if (selectedIndex >= 0 && suggestionListRef.current) {
      const activeElement = suggestionListRef.current.children[selectedIndex] as HTMLElement;
      if (activeElement) {
        activeElement.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selectedIndex]);

  // Hide suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (textareaRef.current && !textareaRef.current.contains(e.target as Node) &&
          suggestionListRef.current && !suggestionListRef.current.contains(e.target as Node)) {
        setTimeout(() => setShowSuggestions(false), 150);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Dynamically generate accurate example queries based on the real database metadata
  const exampleQueries = metrics.length > 0 ? [
    `Total ${metrics[0] || 'revenue'} in 2026`,
    `${metrics[1] || 'profit'} by plant`,
    `${metrics[2] || 'headcount'} in ${departments[0] || 'sales'}`,
    `${metrics[3] || 'expenses'} by region`
  ] : [
    "Total revenue in 2026",
    "Profit by plant",
    "Headcount in sales",
    "Expenses by region"
  ];

  return (
    <div>
      <form onSubmit={handleSubmit} className="space-y-3 relative">
        <div className="relative">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <svg className="h-4 w-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>
          <input
            ref={textareaRef}
            type="text"
            value={query}
            onChange={handleTextChange}
            onFocus={handleTextChange}
            onKeyDown={handleKeyDown as any}
            placeholder="e.g., What was the total revenue in 2026?"
            className="w-full pl-10 pr-3 py-2 text-sm border border-gray-300 rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          
          {showSuggestions && suggestions.length > 0 && (
            <ul 
              ref={suggestionListRef}
              className="absolute z-20 w-full bg-white border border-gray-200 rounded-lg shadow-xl mt-1 max-h-48 overflow-y-auto"
            >
              {suggestions.map((s, idx) => (
                <li 
                  key={idx}
                  className={`px-4 py-2 text-sm cursor-pointer capitalize font-medium border-b border-gray-50 last:border-0 ${
                    selectedIndex === idx ? 'bg-blue-100 text-blue-700' : 'hover:bg-blue-50 text-gray-700'
                  }`}
                  onClick={() => handleSuggestionClick(s)}
                >
                  {s}
                </li>
              ))}
            </ul>
          )}
        </div>

        <button
          type="submit"
          disabled={isLoading || !query.trim()}
          className="w-full px-4 py-2 bg-gradient-to-r from-blue-500 to-blue-600 text-white text-sm font-medium rounded-full shadow-md hover:from-blue-600 hover:to-blue-700 transition-all disabled:from-gray-300 disabled:to-gray-300 disabled:shadow-none disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <>
              <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Analyzing...
            </>
          ) : (
            "Run Query"
          )}
        </button>
      </form>

      {/* Recent Queries / Quick Examples */}
      {recentQueries && recentQueries.length > 0 ? (
        <div className="mt-6 border-t border-gray-100 pt-4">
          <div className="flex items-center justify-between mb-3 cursor-pointer group">
            <h3 className="text-sm font-semibold text-gray-900 group-hover:text-blue-600 transition-colors">Recent Queries</h3>
            <svg className="w-4 h-4 text-gray-400 group-hover:text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 15l7-7 7 7" />
            </svg>
          </div>
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
                className="w-full flex items-center text-left px-2 py-2 rounded text-xs text-gray-600 hover:text-gray-900 hover:bg-gray-50 transition-colors disabled:opacity-50 truncate"
                title={item.query}
              >
                <svg className="w-3.5 h-3.5 mr-2 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="truncate">{item.query}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-4">
          <p className="text-xs text-gray-500 mb-2">Quick examples:</p>
          <div className="space-y-1">
            {[
              "Total revenue in 2026",
              "Profit by plant",
              "Headcount in sales",
              "Expenses by region"
            ].map((example, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => {
                  setQuery(example);
                  onSubmit(example);
                }}
                disabled={isLoading}
                className="w-full text-left px-3 py-2 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded text-xs text-gray-700 transition-colors disabled:opacity-50"
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Interactive Tags */}
      <div className="space-y-6 mt-6 pt-6 border-t border-gray-100">
        <div>
          <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-3">Available Metrics</h3>
          <div className="flex flex-wrap gap-2">
            {(metrics.length > 0 ? metrics : ['Revenue', 'Profit', 'Expenses', 'Headcount', 'Salary', 'Tax', 'Assets', 'Operating Cost']).map(m => (
              <button 
                key={m} 
                type="button"
                onClick={() => setQuery(prev => (prev + ' ' + m).trim() + ' ')}
                className="px-3 py-1 bg-white border border-gray-200 hover:border-gray-300 text-gray-600 text-xs rounded-full transition-colors cursor-pointer hover:bg-gray-50"
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-3">Departments</h3>
          <div className="flex flex-wrap gap-2">
            {(departments.length > 0 ? departments : ['Sales', 'Digital', 'Marketing', 'HR', 'Engineering', 'Finance']).map(d => (
              <button 
                key={d} 
                type="button"
                onClick={() => setQuery(prev => (prev + ' ' + d).trim() + ' ')}
                className="px-3 py-1 bg-white border border-gray-200 hover:border-gray-300 text-gray-600 text-xs rounded-full transition-colors cursor-pointer hover:bg-gray-50"
              >
                {d}
              </button>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-3">Regions</h3>
          <div className="flex flex-wrap gap-2">
            {(regions.length > 0 ? regions : ['North', 'South', 'East', 'West', 'Central']).map(r => (
              <button 
                key={r} 
                type="button"
                onClick={() => setQuery(prev => (prev + ' ' + r).trim() + ' ')}
                className="px-3 py-1 bg-white border border-gray-200 hover:border-gray-300 text-gray-600 text-xs rounded-full transition-colors cursor-pointer hover:bg-gray-50"
              >
                {r}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
