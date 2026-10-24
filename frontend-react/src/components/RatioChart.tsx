import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface RatioChartProps {
  newLeads: number;
  recontactLeads: number;
  totalLeads: number;
  newPhoneLeads: number;
}

const COLORS = ['#1E5BD6', '#0A1F44', '#F5B400'];

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

export function RatioChart({ newLeads, recontactLeads, totalLeads, newPhoneLeads }: RatioChartProps) {
  const data = [
    { name: 'Lead Mới', value: newLeads },
    { name: 'Contact Lại', value: recontactLeads },
  ].filter(d => d.value > 0);

  const recontactRate = totalLeads > 0 ? ((recontactLeads / totalLeads) * 100).toFixed(1) : '0';
  const phoneRate = newLeads > 0 ? ((newPhoneLeads / newLeads) * 100).toFixed(1) : '0';

  return (
    <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card h-full flex flex-col justify-between">
      <div className="mb-3">
        <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-navy">Tỉ lệ chuyển đổi</h3>
        <p className="text-xs text-slate-500 mt-0.5">Phân bổ Lead trong kỳ</p>
      </div>

      {data.length > 0 ? (
        <>
          <ResponsiveContainer width="100%" height={165}>
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={46}
                outerRadius={74}
                paddingAngle={3}
                dataKey="value"
                labelLine={false}
                label={<CustomLabel />}
              >
                {data.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="none" />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  borderRadius: '10px',
                  border: '1px solid #E2E8F0',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(10,31,68,0.06)'
                }}
                formatter={(value: number) => [value.toLocaleString(), 'Lead']}
              />
            </PieChart>
          </ResponsiveContainer>

          <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-2 text-slate-600">
                <span className="w-2 h-2 rounded-full bg-navy inline-block" />
                Tỉ lệ Contact Lại
              </span>
              <span className="font-mono font-semibold text-navy tabular-nums">{recontactRate}%</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-2 text-slate-600">
                <span className="w-2 h-2 rounded-full bg-gold inline-block" />
                SĐT / Tạo mới
              </span>
              <span className="font-mono font-bold text-gold-dark tabular-nums">{phoneRate}%</span>
            </div>
            <div className="h-px bg-slate-100 my-1.5" />
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-500 font-medium">Tổng Lead</span>
              <span className="font-mono font-bold text-navy tabular-nums">{totalLeads.toLocaleString()}</span>
            </div>
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
