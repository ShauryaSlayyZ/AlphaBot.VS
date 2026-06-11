import { DataChart } from './DataChart';

interface ResultsDisplayProps {
  data: any;
}

export function ResultsDisplay({ data }: ResultsDisplayProps) {
  if (!data || !data.results) return null;

  const { results, sql_query, unit, plants_queried, insights, metadata, kpis } = data;

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

  return (
    <div className="p-6 space-y-4">
      {/* Contextual KPIs Bar */}
      {kpis && (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-4 flex flex-col justify-center border-l-4 border-l-blue-500">
            <p className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-1">Revenue</p>
            <p className="text-2xl font-bold text-gray-900">{formatKPI(kpis.revenue)}</p>
          </div>
          <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-4 flex flex-col justify-center border-l-4 border-l-emerald-500">
            <p className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-1">Profit</p>
            <p className="text-2xl font-bold text-gray-900">{formatKPI(kpis.profit)}</p>
          </div>
          <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-4 flex flex-col justify-center border-l-4 border-l-red-500">
            <p className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-1">Expenses</p>
            <p className="text-2xl font-bold text-gray-900">{formatKPI(kpis.expenses)}</p>
          </div>
          <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-4 flex flex-col justify-center border-l-4 border-l-purple-500">
            <p className="text-xs text-gray-500 font-semibold uppercase tracking-wide mb-1">Headcount</p>
            <p className="text-2xl font-bold text-gray-900">{formatHeadcount(kpis.headcount)}</p>
          </div>
        </div>
      )}

      {/* Main Results Card */}
      <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-6">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">Results</h3>
        <div className="flex items-center justify-center">
          <DataChart results={results} unit={unit} />
        </div>
      </div>

      {/* Stats Bar (Moved Below Chart) */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-4 flex flex-col items-center justify-center">
          <p className="text-3xl font-bold text-gray-900">{plants_queried}</p>
          <p className="text-xs text-gray-400 mt-1 uppercase tracking-wide">Plants Queried</p>
        </div>
        <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-4 flex flex-col items-center justify-center">
          <p className="text-3xl font-bold text-gray-900">{Math.round(metadata?.backend_ms || 0)}ms</p>
          <p className="text-xs text-gray-400 mt-1 uppercase tracking-wide">Response Time</p>
        </div>
        <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-4 flex flex-col items-center justify-center">
          <p className="text-3xl font-bold text-gray-900">{unit}</p>
          <p className="text-xs text-gray-400 mt-1 uppercase tracking-wide">Unit</p>
        </div>
      </div>

      {/* Two Column Layout */}
      <div className="grid grid-cols-2 gap-4">
        {/* SQL Query */}
        <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-6 flex flex-col">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Generated SQL</h3>
          <div className="flex-1 bg-gray-50 border border-gray-100 rounded-lg p-4 overflow-x-auto">
            <pre className="text-[13px] leading-relaxed text-gray-800 font-mono">
              {sql_query.split('\n').map((line: string, i: number) => (
                <div key={i} className="flex">
                  <span className="w-6 text-gray-400 select-none mr-2">{i + 1}</span>
                  <span dangerouslySetInnerHTML={{
                    __html: line
                      .replace(/(SELECT|FROM|WHERE|GROUP BY|ORDER BY|AND|OR|AS|SUM)/g, '<span class="text-blue-600 font-semibold">$1</span>')
                      .replace(/('[^']*')/g, '<span class="text-emerald-600">$1</span>')
                  }} />
                </div>
              ))}
            </pre>
          </div>
        </div>

        {/* Raw Data */}
        <div className="bg-white border border-gray-100 shadow-sm rounded-xl p-6 flex flex-col">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Data Table</h3>
          <div className="flex-1 overflow-auto rounded-lg border border-gray-50">
            <table className="w-full text-xs text-left">
              <thead className="bg-gray-50/80 sticky top-0">
                <tr>
                  {Object.keys(results[0] || {}).map((key) => (
                    <th key={key} className="py-3 px-4 text-gray-500 font-bold uppercase tracking-wider text-[10px]">
                      {key.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {results.map((row: any, idx: number) => (
                  <tr key={idx} className="hover:bg-gray-50/50 transition-colors">
                    {Object.values(row).map((value: any, cellIdx: number) => (
                      <td key={cellIdx} className="py-3 px-4 text-gray-900">
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
    </div>
  );
}
