import React from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface StatsPieChartProps {
  title: string;
  subtitle: string;
  stats: Record<string, number> | undefined;
  colorMap?: Record<string, string>;
  unit?: string;
  headerAction?: React.ReactNode;
}

const COLORS = ['#1E5BD6', '#0A1F44', '#F5B400', '#3B82F6', '#64748B', '#10B981', '#94A3B8', '#CBD5E1'];

const CustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }: any) => {
  if (percent < 0.06) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
};

export function StatsPieChart({ title, subtitle, stats, colorMap, unit = 'Lead', headerAction }: StatsPieChartProps) {
  if (!stats) return null;

  const data = Object.entries(stats)
    .filter(([_, value]) => value > 0)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  const total = data.reduce((acc, curr) => acc + curr.value, 0);

  const getColor = (name: string, index: number) => {
    if (colorMap && colorMap[name]) return colorMap[name];
    return COLORS[index % COLORS.length];
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">{title}</h3>
          <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
        </div>
        {headerAction && (
          <div className="shrink-0">
            {headerAction}
          </div>
        )}
      </div>

      {data.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={170}>
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={42}
                outerRadius={76}
                paddingAngle={2}
                dataKey="value"
                labelLine={false}
                label={<CustomLabel />}
              >
                {data.map((item, index) => (
                  <Cell key={`cell-${index}`} fill={getColor(item.name, index)} stroke="none" />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  borderRadius: '10px',
                  border: '1px solid #E2E8F0',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(10,31,68,0.06)'
                }}
                formatter={(value: number) => [value.toLocaleString(), unit]}
              />
            </PieChart>
          </ResponsiveContainer>

          <div className="mt-3 pt-3 border-t border-slate-100 max-h-[116px] overflow-y-auto space-y-1.5 pr-1 custom-scrollbar">
            {data.map((item, index) => (
              <div key={item.name} className="flex items-center justify-between text-xs py-0.5">
                <span className="flex items-center gap-2 text-slate-600 truncate mr-2">
                  <span
                    className="w-2 h-2 rounded-full inline-block shrink-0"
                    style={{ backgroundColor: getColor(item.name, index) }}
                  />
                  <span className="truncate">{item.name}</span>
                </span>
                <span className="font-mono font-semibold text-navy shrink-0 tabular-nums">
                  {item.value.toLocaleString()}
                  <span className="text-slate-400 font-normal ml-1">
                    ({((item.value / total) * 100).toFixed(1)}%)
                  </span>
                </span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="flex items-center justify-center h-[200px] text-slate-300 text-xs">
          Không có dữ liệu
        </div>
      )}
    </div>
  );
}
