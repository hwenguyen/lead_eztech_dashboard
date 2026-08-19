import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface StatsPieChartProps {
  title: string;
  subtitle: string;
  stats: Record<string, number> | undefined;
}

const COLORS = ['#1E5BD6', '#10B981', '#F59E0B', '#EF4444', '#0A1F44', '#FFC107', '#E6F0FF', '#4B5563'];

const CustomLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percent }: any) => {
  if (percent < 0.05) return null;
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

export function StatsPieChart({ title, subtitle, stats }: StatsPieChartProps) {
  if (!stats) return null;

  const data = Object.entries(stats)
    .filter(([_, value]) => value > 0)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);

  const total = data.reduce((acc, curr) => acc + curr.value, 0);

  return (
    <div className="bg-white rounded-2xl border border-[#E5E7EB] p-6 shadow-sm">
      <div className="mb-4">
        <h3 className="text-base font-semibold text-navy">{title}</h3>
        <p className="text-xs text-[#4B5563] mt-0.5">{subtitle}</p>
      </div>

      {data.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={80}
                paddingAngle={2}
                dataKey="value"
                labelLine={false}
                label={<CustomLabel />}
              >
                {data.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => [value, 'Lead']} />
            </PieChart>
          </ResponsiveContainer>

          <div className="mt-4 max-h-[120px] overflow-y-auto space-y-2 pr-1 custom-scrollbar">
            {data.map((item, index) => (
              <div key={item.name} className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-2 text-gray-600 truncate mr-2">
                  <span 
                    className="w-2.5 h-2.5 rounded-full inline-block shrink-0" 
                    style={{ backgroundColor: COLORS[index % COLORS.length] }} 
                  />
                  <span className="truncate">{item.name}</span>
                </span>
                <span className="font-semibold text-gray-800 shrink-0">
                  {item.value.toLocaleString()} 
                  <span className="text-[#4B5563] font-normal ml-1">
                    ({((item.value / total) * 100).toFixed(1)}%)
                  </span>
                </span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="flex items-center justify-center h-[200px] text-gray-300 text-sm">
          Không có dữ liệu
        </div>
      )}
    </div>
  );
}
